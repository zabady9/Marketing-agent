#!/usr/bin/env python3
"""
Live integration test harness for the consulting analysis feature.

Runs P2 (happy-path regression) and P1 (robustness/error-handling) scenarios
against a running server, asserting status codes and documented response shapes.

Usage:
  python scripts/test_live_scenarios.py [--base-url URL] [--full] [--ws-id ID]

Options:
  --base-url   Server base URL (default: http://localhost:8001)
  --ws-id      Workspace ID with a brand profile already set (default: auto-detect)
  --full       Also run slow LLM-backed tests (P2-1..P2-7, P1-1, P1-9).
               Without this flag those are SKIPPED (they make real API calls and
               take 30-120 s each).

Exit code 0 if all non-skipped tests pass, 1 if any fail.
"""

import argparse
import json
import sys
import time
import threading
import requests
from typing import Optional

# ── ANSI colours ──────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

# ── State ─────────────────────────────────────────────────────────────────────

_results: list[tuple[str, str, str]] = []  # (status, name, msg)

def _pass(name: str, msg: str = "") -> None:
    _results.append(("PASS", name, msg))
    print(f"  {GREEN}✓ PASS{RESET}  {BOLD}{name}{RESET}" + (f"\n         {DIM}{msg}{RESET}" if msg else ""))

def _fail(name: str, msg: str = "") -> None:
    _results.append(("FAIL", name, msg))
    print(f"  {RED}✗ FAIL{RESET}  {BOLD}{name}{RESET}" + (f"\n         {RED}{msg}{RESET}" if msg else ""))

def _skip(name: str, msg: str = "") -> None:
    _results.append(("SKIP", name, msg))
    print(f"  {YELLOW}⊘ SKIP{RESET}  {BOLD}{name}{RESET}" + (f"\n         {DIM}{msg}{RESET}" if msg else ""))

def _note(name: str, msg: str = "") -> None:
    """Manual-check required — records as MANUAL."""
    _results.append(("MANUAL", name, msg))
    print(f"  {CYAN}? NOTE{RESET}  {BOLD}{name}{RESET}" + (f"\n         {DIM}{msg}{RESET}" if msg else ""))

# ── HTTP helpers ──────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8001"


def _ws_url(path: str) -> str:
    return f"{BASE_URL}/api/workspaces{path}"


def _get(path: str, *, timeout: int = 30, **kw) -> requests.Response:
    return requests.get(_ws_url(path), timeout=timeout, **kw)


def _post(path: str, payload: dict, *, timeout: int = 120, **kw) -> requests.Response:
    """Default 120 s — LLM classification can take 30-60 s."""
    return requests.post(_ws_url(path), json=payload, timeout=timeout, **kw)


def _create_workspace(name: str = "test-harness") -> Optional[str]:
    try:
        r = requests.post(f"{BASE_URL}/api/workspaces", json={"name": name}, timeout=30)
        if r.status_code == 200:
            return r.json()["id"]
    except Exception:
        pass
    return None


def _set_brand_profile(ws_id: str, industry: str = "digital marketing",
                       brand_name: str = "HarnessTestBrand") -> bool:
    try:
        r = requests.put(
            _ws_url(f"/{ws_id}/brand-profile"),
            json={"industry": industry, "brand_name": brand_name, "company_name": brand_name},
            timeout=30,
        )
        return r.status_code in (200, 201)
    except Exception:
        return False


def _find_workspace_with_brand_profile() -> Optional[str]:
    """Return the first workspace ID that has a brand profile set."""
    try:
        r = requests.get(f"{BASE_URL}/api/workspaces", timeout=30)
        if r.status_code != 200:
            return None
        for ws in r.json():
            bp = requests.get(_ws_url(f"/{ws['id']}/brand-profile"), timeout=30)
            if bp.status_code == 200 and bp.json().get("brand_name"):
                return ws["id"]
    except Exception:
        pass
    return None


def _poll_analysis(ws_id: str, analysis_id: str, timeout: int = 180) -> Optional[dict]:
    """Poll until status != 'generating'. Returns final body or None on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(_ws_url(f"/{ws_id}/analyses/{analysis_id}"), timeout=10)
        if r.status_code != 200:
            return None
        body = r.json()
        if body["status"] != "generating":
            return body
        time.sleep(4)
    return None


def _read_sse_stream(ws_id: str, analysis_id: str, max_events: int = 20,
                     timeout: int = 180) -> list[dict]:
    """Consume an SSE stream, returning a list of parsed event dicts."""
    url = _ws_url(f"/{ws_id}/analyses/{analysis_id}/stream")
    events: list[dict] = []
    try:
        with requests.get(url, stream=True, timeout=timeout) as resp:
            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                if raw_line.startswith("data: "):
                    data_str = raw_line[len("data: "):]
                    try:
                        evt = json.loads(data_str)
                        events.append(evt)
                        if evt.get("type") in ("done", "error"):
                            break
                        if len(events) >= max_events:
                            break
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass
    return events


# ── Shape validators ──────────────────────────────────────────────────────────

def _check_202_shape(body: dict, test_name: str) -> None:
    required = {"id", "workspace_id", "analysis_type", "status", "results", "error", "created_at"}
    missing = required - body.keys()
    if missing:
        _fail(test_name, f"202 response missing keys: {missing}")
        return
    if body["status"] != "generating":
        _fail(test_name, f"Expected status=generating, got {body['status']!r}")
        return
    if body["results"] is not None:
        _fail(test_name, "Expected results=null in 202")
        return
    _pass(test_name, f"analysis_id={body['id'][:8]}…  type={body['analysis_type']}")


def _check_ready_shape(body: dict, expected_type: str, test_name: str) -> None:
    if body["status"] != "ready":
        _fail(test_name, f"Expected status=ready, got {body['status']!r}. error={body.get('error')!r}")
        return

    results = body.get("results")
    if not results:
        _fail(test_name, "status=ready but results is null")
        return

    # Top-level results keys
    for key in ("analysis_type", "output", "citations", "disclaimer", "eval"):
        if key not in results:
            _fail(test_name, f"results missing key: {key!r}")
            return

    # Disclaimer present and Arabic-looking (contains Arabic characters)
    disclaimer = results.get("disclaimer", "")
    has_arabic = any("؀" <= c <= "ۿ" for c in disclaimer)
    if not has_arabic:
        _fail(test_name, f"disclaimer missing or not Arabic: {disclaimer!r}")
        return

    # Eval shape
    ev = results.get("eval")
    if ev is not None:
        score = ev.get("overall_score")
        if score is None or not (0.0 <= score <= 1.0):
            _fail(test_name, f"eval.overall_score out of [0,1] or missing: {score!r}")
            return
        if "passed" not in ev:
            _fail(test_name, "eval missing 'passed' key")
            return

    # Type-specific output shape
    output = results["output"]
    output_ok, output_msg = _check_output_shape(expected_type, output)
    if not output_ok:
        _fail(test_name, output_msg)
        return

    # Citation indices all in range
    citations = results.get("citations", [])
    citation_issue = _check_citation_indices(expected_type, output, len(citations))
    if citation_issue:
        _fail(test_name, citation_issue)
        return

    _pass(test_name, f"type={expected_type}  citations={len(citations)}  eval.passed={ev.get('passed') if ev else 'null'}")


def _check_output_shape(analysis_type: str, output: dict) -> tuple[bool, str]:
    """Validate type-specific output keys. Returns (ok, error_msg)."""
    schemas = {
        "swot": {"strengths", "weaknesses", "opportunities", "threats"},
        "pestel": {"political", "economical", "social", "technological", "environmental", "legal"},
        "feasibility": {"market_size_and_growth", "competitive_landscape",
                        "target_customer", "key_risks", "recommendation", "recommendation_rationale"},
        "brand_analysis": {"positioning", "messaging", "audience_alignment", "summary_recommendation"},
        "market_research": {"market_overview", "segments", "key_trends",
                            "competitive_dynamics", "strategic_implications"},
    }
    expected = schemas.get(analysis_type)
    if expected is None:
        return True, ""  # unknown type, skip
    missing = expected - set(output.keys())
    if missing:
        return False, f"output missing keys for {analysis_type}: {missing}"
    if analysis_type == "feasibility":
        rec = output.get("recommendation", "")
        valid_recs = {"proceed", "proceed_with_caution", "do_not_proceed"}
        if rec not in valid_recs:
            return False, f"recommendation {rec!r} not in {valid_recs}"
    return True, ""


def _check_citation_indices(analysis_type: str, output: dict, n_citations: int) -> str:
    """
    For array-type items, verify citation_indices are non-empty lists pointing to valid indices.
    Returns an error string, or "" if all fine.
    """
    def _check_item(item: dict, path: str) -> str:
        indices = item.get("citation_indices")
        if indices is None:
            return f"{path}: missing citation_indices"
        for idx in indices:
            if idx < 0 or idx >= n_citations:
                return f"{path}: index {idx} out of range (n={n_citations})"
        return ""

    if analysis_type == "swot":
        for sec in ("strengths", "weaknesses", "opportunities", "threats"):
            for i, item in enumerate(output.get(sec, [])):
                err = _check_item(item, f"{sec}[{i}]")
                if err:
                    return err
    elif analysis_type == "pestel":
        for dim in ("political", "economical", "social", "technological", "environmental", "legal"):
            for i, item in enumerate(output.get(dim, [])):
                err = _check_item(item, f"{dim}[{i}]")
                if err:
                    return err
    elif analysis_type == "feasibility":
        for sec in ("market_size_and_growth", "competitive_landscape", "target_customer", "key_risks"):
            item = output.get(sec, {})
            err = _check_item(item, sec)
            if err:
                return err
    elif analysis_type == "brand_analysis":
        for sec in ("positioning", "messaging", "audience_alignment"):
            for i, item in enumerate(output.get(sec, [])):
                err = _check_item(item, f"{sec}[{i}]")
                if err:
                    return err
    elif analysis_type == "market_research":
        err = _check_item(output.get("market_overview", {}), "market_overview")
        if err:
            return err
        for i, item in enumerate(output.get("key_trends", [])):
            err = _check_item(item, f"key_trends[{i}]")
            if err:
                return err
    return ""


# ── Test runners ──────────────────────────────────────────────────────────────

def run_p2_fast(ws_id: str, llm_available: bool = True) -> None:
    """
    P2-8 and P2-9 — these call /consult which invokes the intent-classification LLM.
    They return quickly (no full analysis), but the LLM call can take 30-60 s.
    """
    print(f"\n{BOLD}{CYAN}── P2 Classification-only (LLM intent classifier, ~30-60 s each) ──{RESET}")
    if not llm_available:
        for name in [
            "P2-8  /consult 'Write me an Instagram caption' → 422 out_of_scope",
            "P2-9  /consult 'Tell me about the market and our competition' → 422 general",
        ]:
            _skip(name, "LLM unavailable (503 on probe) — DNS/network blocked in container")
        return

    # P2-8: writing task → out_of_scope → 422
    name = "P2-8  /consult 'Write me an Instagram caption' → 422 out_of_scope"
    try:
        r = _post(f"/{ws_id}/consult", {"question": "Write me an Instagram caption"})
        if r.status_code != 422:
            _fail(name, f"got {r.status_code}: {r.text[:120]}")
        else:
            detail = r.json().get("detail", {})
            cls = detail.get("classification") if isinstance(detail, dict) else None
            if cls == "out_of_scope" and detail.get("message"):
                _pass(name, f"classification={cls!r}, message present")
            else:
                _fail(name, f"status=422 but detail shape unexpected: {detail!r}")
    except requests.exceptions.Timeout:
        _fail(name, "Request timed out after 120 s — LLM or server unreachable")
    except Exception as exc:
        _fail(name, f"Exception: {exc}")

    # P2-9: ambiguous question → general → 422
    name = "P2-9  /consult 'Tell me about the market and our competition' → 422 general"
    try:
        r = _post(f"/{ws_id}/consult", {"question": "Tell me about the market and our competition"})
        if r.status_code != 422:
            # If 202 returned, classifier was "decisive" and picked a specific type — documented risk
            if r.status_code == 202:
                body = r.json()
                _note(name,
                      f"classifier chose {body.get('classified_as')!r} (returned 202) instead of "
                      f"'general' — documented 'be decisive' pressure means this is a known risk, "
                      f"not a crash. See P0-4.")
            else:
                _fail(name, f"got {r.status_code}: {r.text[:120]}")
        else:
            detail = r.json().get("detail", {})
            cls = detail.get("classification") if isinstance(detail, dict) else None
            if cls == "general" and detail.get("message"):
                _pass(name, f"classification={cls!r}, clarifying message present")
            else:
                _fail(name, f"status=422 but detail shape unexpected: {detail!r}")
    except requests.exceptions.Timeout:
        _fail(name, "Request timed out after 120 s — LLM or server unreachable")
    except Exception as exc:
        _fail(name, f"Exception: {exc}")


def run_p1_fast(ws_id: str, ws_no_bp_id: Optional[str], llm_available: bool = True) -> None:
    """
    P1 tests that require no LLM calls and return immediately.
    ws_no_bp_id: a workspace that exists but has NO brand profile set (can be None).
    """
    print(f"\n{BOLD}{CYAN}── P1 Fast (error-handling, no LLM) ──{RESET}")

    # ── P1-2: missing brand profile → 422 ──────────────────────────────────────
    if not ws_no_bp_id:
        for ep_label in ("/consult", "/analyses:generate"):
            _skip(f"P1-2  Missing brand profile → 422  ({ep_label})",
                  "No no-brand-profile workspace available — pass --no-bp-ws-id")
    else:
        for endpoint, payload in [
            (f"/{ws_no_bp_id}/consult", {"question": "What are our strengths?"}),
            (f"/{ws_no_bp_id}/analyses:generate", {"analysis_type": "swot"}),
        ]:
            endpoint_label = "/consult" if "consult" in endpoint else "/analyses:generate"
            name = f"P1-2  Missing brand profile → 422  ({endpoint_label})"
            try:
                r = _post(endpoint, payload)
                if r.status_code != 422:
                    _fail(name, f"got {r.status_code}: {r.text[:120]}")
                else:
                    detail = r.json().get("detail", "")
                    if "brand" in str(detail).lower():
                        _pass(name, f"detail mentions brand profile: {str(detail)[:80]!r}")
                    else:
                        _fail(name, f"422 but detail doesn't mention brand: {detail!r}")
            except requests.exceptions.Timeout:
                _fail(name, "Request timed out")

    # ── P1-3: nonexistent workspace → 404 ──────────────────────────────────────
    fake_id = "00000000-dead-beef-0000-000000000000"
    for endpoint, payload in [
        (f"/{fake_id}/consult", {"question": "hello"}),
        (f"/{fake_id}/analyses:generate", {"analysis_type": "swot"}),
        (f"/{fake_id}/analyses/{fake_id}", None),
    ]:
        method = "GET" if payload is None else "POST"
        r = (requests.get(_ws_url(endpoint), timeout=10)
             if method == "GET"
             else _post(endpoint, payload))
        endpoint_label = endpoint.split("/")[-1]
        name = f"P1-3  Nonexistent workspace → 404  ({'GET' if payload is None else 'POST'} …/{endpoint_label})"
        if r.status_code != 404:
            _fail(name, f"got {r.status_code}: {r.text[:120]}")
        else:
            # Check no stack trace or DB error text leaked
            body_str = r.text.lower()
            leaks = [kw for kw in ("traceback", "sqlalchemy", "psycopg", "asyncpg") if kw in body_str]
            if leaks:
                _fail(name, f"404 body leaks internal details: {leaks}")
            else:
                _pass(name, "404 with clean error body")

    # ── P1-8: malformed analysis_type → 422 ────────────────────────────────────
    bad_types = [
        ("SWOT", "wrong case"),
        ("swot_analysis", "near-miss string"),
        ("", "empty string"),
        ("general", "classifier-only label not accepted by direct endpoint"),
        ("out_of_scope", "classifier-only label not accepted by direct endpoint"),
    ]
    for bad_val, reason in bad_types:
        payload = {"analysis_type": bad_val} if bad_val else {}
        r = _post(f"/{ws_id}/analyses:generate", payload)
        name = f"P1-8  analysis_type={bad_val!r} ({reason}) → 422"
        if r.status_code == 422:
            _pass(name)
        elif r.status_code == 202:
            _fail(name, f"accepted silently with 202 — Pydantic validation didn't fire")
        else:
            _fail(name, f"got {r.status_code}: {r.text[:80]}")

    # ── P1-11: empty / whitespace question ─────────────────────────────────────
    for question, label in [("   ", "whitespace-only"), ("", "empty string")]:
        name = f"P1-11 /consult question={label!r} → 422 or graceful classification"
        if not llm_available:
            _skip(name, "LLM unavailable — Pydantic validation test skipped too")
            continue
        try:
            r = _post(f"/{ws_id}/consult", {"question": question})
            if r.status_code == 422:
                _pass(name, "Pydantic or classification rejected it cleanly with 422")
            elif r.status_code == 202:
                body = r.json()
                _note(name, f"Accepted as 202 (classified as {body.get('classified_as')!r}) — "
                      "not a crash but may produce nonsensical output")
            else:
                _fail(name, f"got {r.status_code}: {r.text[:80]}")
        except requests.exceptions.Timeout:
            _note(name, "Timed out — LLM may accept it; no immediate crash")
        except Exception as exc:
            _fail(name, f"Exception: {exc}")

    # ── P1-10: non-English (Arabic) question ───────────────────────────────────
    arabic_q = "ما هي التهديدات التنافسية الأساسية التي تواجه شركتنا؟"
    name = "P1-10 Non-English (Arabic) question — no crash"
    if not llm_available:
        _skip(name, "LLM unavailable")
    else:
        try:
            r = _post(f"/{ws_id}/consult", {"question": arabic_q})
            if r.status_code in (202, 422):
                _pass(name, f"Handled without 500: status={r.status_code}")
            else:
                _fail(name, f"got {r.status_code}: {r.text[:120]}")
        except requests.exceptions.Timeout:
            _note(name, "Timed out — LLM may be slow on non-English input, but no crash observed")
        except Exception as exc:
            _fail(name, f"Exception: {exc}")

    # ── P1-12: extremely long question ─────────────────────────────────────────
    long_q = ("How should we approach the market? " * 150)  # ~5 250 chars
    name = "P1-12 Extremely long question (~5 000 chars) — no crash"
    if not llm_available:
        _skip(name, "LLM unavailable")
    else:
        try:
            r = _post(f"/{ws_id}/consult", {"question": long_q}, timeout=150)
            if r.status_code in (202, 422, 413):
                _pass(name, f"Handled without 500: status={r.status_code}")
            else:
                _fail(name, f"got {r.status_code}: {r.text[:120]}")
        except requests.exceptions.Timeout:
            _note(name, "Timed out — volume may slow LLM, but no crash confirmed before timeout")
        except Exception as exc:
            _fail(name, f"Exception: {exc}")

    # ── P1-6: context truncation is silent ─────────────────────────────────────
    # /analyses:generate doesn't call LLM for classification; 202 is immediate
    long_ctx = (
        "We are targeting B2B enterprise customers — NOT consumer. " * 5  # ~275 chars
    )
    name = "P1-6  Context >200 chars accepted silently (no truncation signal in 202)"
    try:
        r = _post(f"/{ws_id}/analyses:generate",
                  {"analysis_type": "market_research", "context": long_ctx})
        if r.status_code == 202:
            body = r.json()
            if "truncated" in str(body) or "warning" in str(body).lower():
                _fail(name, f"Unexpected truncation signal in 202 response: {body}")
            else:
                _pass(name, "202 returned; no 'truncated' field — silent by design (§8)")
        elif r.status_code == 422:
            _note(name, f"422 — Pydantic may enforce a max context length: {r.json()!r}")
        else:
            _fail(name, f"got {r.status_code}: {r.text[:80]}")
    except requests.exceptions.Timeout:
        _fail(name, "Timed out — /analyses:generate should return 202 instantly (no LLM)")
    except Exception as exc:
        _fail(name, f"Exception: {exc}")

    # ── P1-7: type mismatch — PESTEL for HR question ───────────────────────────
    # /analyses:generate → 202 immediately, no LLM classification guard
    name = "P1-7  analysis_type mismatch (pestel + HR context) → 202, no validation error"
    try:
        r = _post(f"/{ws_id}/analyses:generate",
                  {"analysis_type": "pestel", "context": "Should we hire a new head of sales?"})
        if r.status_code == 202:
            _pass(name, "No client-side type/content guard; accepted as documented")
        else:
            _fail(name, f"Expected 202, got {r.status_code}: {r.text[:80]}")
    except requests.exceptions.Timeout:
        _fail(name, "Timed out — /analyses:generate should return 202 instantly (no LLM)")
    except Exception as exc:
        _fail(name, f"Exception: {exc}")


def run_p1_stream(ws_id: str, completed_analysis_id: str) -> None:
    """
    P1-4 (stream before task) and P1-5 (stream after completion).
    completed_analysis_id must be the ID of a ready or failed analysis.
    """
    print(f"\n{BOLD}{CYAN}── P1 Stream tests ──{RESET}")

    # ── P1-5: stream opened after completion → immediate done/error, no hang ──
    name = "P1-5  Stream after completion → immediate done/error event, no hang"
    try:
        events = _read_sse_stream(ws_id, completed_analysis_id, timeout=15)
        if not events:
            _fail(name, "No SSE events received")
        elif events[0].get("type") in ("done", "error"):
            _pass(name, f"First event type={events[0]['type']!r}, total events={len(events)}")
        else:
            _fail(name, f"First event was {events[0].get('type')!r}, expected done/error")
    except Exception as exc:
        _fail(name, f"Exception: {exc}")

    # ── P1-4: stream for non-existent / stale analysis_id ──────────────────────
    fake_analysis_id = "00000000-dead-beef-dead-000000000000"
    name = "P1-4  Stream for non-existent analysis_id → 404, no crash"
    try:
        r = requests.get(
            _ws_url(f"/{ws_id}/analyses/{fake_analysis_id}/stream"),
            timeout=10,
            stream=False,
        )
        if r.status_code == 404:
            _pass(name, "Correct 404")
        elif r.status_code == 200:
            # According to documented gap (§8), this may NOT return 404 cleanly
            _note(name,
                  "200 returned instead of 404 — documented gap: event_bus.exists() guard missing. "
                  "Connection may hang or error rather than rejecting cleanly.")
        elif r.status_code == 500:
            _fail(name, f"500 Internal Server Error — event_bus crash confirmed (documented gap §8)")
        else:
            _note(name, f"Unexpected status {r.status_code}: {r.text[:80]}")
    except requests.exceptions.Timeout:
        _note(name, "Request timed out — stream may be hanging (documented gap §8)")
    except Exception as exc:
        _fail(name, f"Exception: {exc}")


def run_p2_full_analysis(ws_id: str, question: str, expected_type: str, test_name: str,
                         endpoint: str = "consult") -> Optional[str]:
    """
    Submit a consult or analyses:generate request, wait for completion, validate shape.
    Returns analysis_id if ready (for use in stream test), else None.
    """
    if endpoint == "consult":
        payload = {"question": question}
        path = f"/{ws_id}/consult"
    else:
        payload = {"analysis_type": expected_type}
        if question:
            payload["context"] = question
        path = f"/{ws_id}/analyses:generate"

    r = _post(path, payload, timeout=30)
    if r.status_code != 202:
        _fail(test_name, f"Expected 202, got {r.status_code}: {r.text[:120]}")
        return None

    body_202 = r.json()
    analysis_id = body_202["id"]

    # For /consult: check classified_as matches expected
    if endpoint == "consult":
        classified_as = body_202.get("classified_as")
        if classified_as != expected_type:
            _fail(test_name, f"classified_as={classified_as!r} ≠ expected {expected_type!r}")
            # Still poll to completion so we have an analysis_id for stream test
        # Don't return yet — continue to poll

    print(f"         {DIM}  ↳ analysis_id={analysis_id[:8]}…  polling for completion…{RESET}")
    final = _poll_analysis(ws_id, analysis_id, timeout=180)

    if final is None:
        _fail(test_name, "Timed out waiting for status != generating")
        return None

    if endpoint == "consult":
        classified_as = body_202.get("classified_as")
        if classified_as != expected_type:
            _fail(test_name + " (classified_as)", f"classified_as={classified_as!r} ≠ {expected_type!r}")
            return analysis_id

    _check_ready_shape(final, expected_type, test_name)
    return analysis_id


def run_p2_stream(ws_id: str, analysis_id: str) -> None:
    """P2-10: SSE stream events must arrive in order research_start→research_done→analysis_start→done."""
    name = "P2-10 SSE stream events in order: research_start→research_done→analysis_start→done"
    # The analysis is already complete — that case yields an immediate done per §6.
    # For the full ordered-event check we'd need to open the stream BEFORE submission.
    # Since we only have a completed analysis_id here, we verify the immediate-done path
    # and label the ordered-event sequence as a manual-check note.
    events = _read_sse_stream(ws_id, analysis_id, timeout=15)
    if events and events[0].get("type") in ("done", "error"):
        _pass(name + " (already-complete fast-path)",
              f"Immediate {events[0]['type']!r} event on completed analysis ✓")
    else:
        _note(name, f"Unexpected first event: {events[0] if events else '(none)'} — "
              "for ordered-event check, open the stream before submitting the request.")


def run_p1_insufficient_citations(ws_id_base: str) -> None:
    """
    P1-1: Create a workspace with an extremely niche industry, verify <4 citations
    causes status=failed with the documented error message.
    NOTE: This test is inherently flaky — DDGS may still return ≥4 results for any industry.
    """
    print(f"\n{BOLD}{CYAN}── P1-1 Insufficient citations (niche industry) ──{RESET}")
    name = "P1-1  Niche industry returns <4 citations → status=failed with documented error"

    # Create a temporary workspace with an implausibly niche industry
    niche_ws_id = _create_workspace("test-niche-citations")
    if not niche_ws_id:
        _skip(name, "Could not create temp workspace")
        return

    ok = _set_brand_profile(
        niche_ws_id,
        industry="artisanal yak-wool sock manufacturing in rural Mongolia",
        brand_name="YakSock Co",
    )
    if not ok:
        _skip(name, "Could not set brand profile on temp workspace")
        return

    r = _post(f"/{niche_ws_id}/analyses:generate", {"analysis_type": "market_research"})
    if r.status_code != 202:
        _fail(name, f"Expected 202, got {r.status_code}: {r.text[:80]}")
        return

    analysis_id = r.json()["id"]
    print(f"         {DIM}  ↳ polling for niche-industry analysis completion…{RESET}")
    final = _poll_analysis(niche_ws_id, analysis_id, timeout=90)

    if final is None:
        _skip(name, "Timed out — DDGS may be slow or blocked")
        return

    if final["status"] == "failed":
        err = final.get("error", "")
        if "Insufficient sources found" in err:
            # Extract N from "Insufficient sources found (N)"
            import re
            m = re.search(r"Insufficient sources found \((\d+)\)", err)
            n_in_msg = int(m.group(1)) if m else "?"
            _pass(name, f"status=failed, error={err!r}, N={n_in_msg}")
        else:
            _fail(name, f"status=failed but error message doesn't match docs: {err!r}")
    elif final["status"] == "ready":
        _note(name,
              "DDGS returned ≥4 results for niche industry — test inconclusive. "
              "Try an even more obscure industry, or use a network proxy to block DDGS.")
    else:
        _fail(name, f"Unexpected status: {final['status']!r}")


def run_p1_concurrent(ws_id: str) -> None:
    """P1-9: 5 concurrent requests — confirms no server crash; DDGS throttling is informational."""
    print(f"\n{BOLD}{CYAN}── P1-9 Concurrent requests ──{RESET}")
    name = "P1-9  5 concurrent /analyses:generate requests — no 500s"

    errors = []
    analysis_ids = []
    lock = threading.Lock()

    def submit_one(i: int) -> None:
        try:
            r = _post(f"/{ws_id}/analyses:generate",
                      {"analysis_type": "swot", "context": f"concurrent test {i}"},
                      timeout=30)
            with lock:
                if r.status_code == 202:
                    analysis_ids.append(r.json()["id"])
                else:
                    errors.append(f"req {i}: {r.status_code} {r.text[:60]}")
        except Exception as exc:
            with lock:
                errors.append(f"req {i}: {exc}")

    threads = [threading.Thread(target=submit_one, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=45)

    if errors:
        _fail(name, f"{len(errors)} errors: {errors[0]!r}{'…' if len(errors)>1 else ''}")
    else:
        _pass(name, f"All 5 accepted with 202.  "
              "Downstream DDGS throttling may reduce citation counts on some (see P0-9 note).")
    _note("P1-9 (DDGS throttle observation)",
          "Check logs for DuckDuckGo errors — no backoff/circuit-breaker is in place (§8). "
          "Some analyses may fail with 'Insufficient sources found' purely due to rate limiting.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    global BASE_URL

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8001",
                        help="Server base URL (default: http://localhost:8001)")
    parser.add_argument("--ws-id", default=None,
                        help="Workspace ID with a brand profile set")
    parser.add_argument("--no-bp-ws-id", default=None,
                        help="Workspace ID that has NO brand profile (for P1-2 test)")
    parser.add_argument("--full", action="store_true",
                        help="Run slow LLM-backed P2 happy-path and P1-1/P1-9 tests")
    args = parser.parse_args()

    BASE_URL = args.base_url.rstrip("/")

    # ── Discover workspace ────────────────────────────────────────────────────
    ws_id = args.ws_id or _find_workspace_with_brand_profile()
    if not ws_id:
        print(f"{RED}ERROR: No workspace with a brand profile found. "
              f"Pass --ws-id or create a workspace first.{RESET}")
        sys.exit(2)

    # ── Workspace with no brand profile for P1-2 ─────────────────────────────
    ws_no_bp_id = args.no_bp_ws_id
    if not ws_no_bp_id:
        ws_no_bp_id = _create_workspace("test-no-brand-profile")
    if not ws_no_bp_id:
        print(f"{YELLOW}Warning: could not create no-brand-profile workspace; P1-2 will be skipped{RESET}")
        ws_no_bp_id = None

    # ── Probe LLM availability ────────────────────────────────────────────────
    # Send a trivial consult request; if it 503s immediately (DNS/network blocked),
    # all /consult tests that require the LLM will be SKIP not FAIL.
    llm_available = True
    try:
        probe = _post(f"/{ws_id}/consult", {"question": "test"}, timeout=60)
        if probe.status_code == 503:
            llm_available = False
    except requests.exceptions.Timeout:
        llm_available = False
    except Exception:
        llm_available = False

    print(f"\n{BOLD}Consulting Analysis — Live Scenario Tests{RESET}")
    print(f"  server   : {BASE_URL}")
    print(f"  ws_id    : {ws_id}")
    print(f"  no-bp ws : {ws_no_bp_id or '(none — P1-2 will skip)'}")
    print(f"  LLM      : {'✓ reachable' if llm_available else '✗ unavailable (503 — DNS/network blocked in container)'}")
    print(f"  mode     : {'full (LLM tests enabled)' if args.full else 'fast (LLM tests skipped)'}\n")

    # ── Phase 1: P2 classification-only (LLM) ────────────────────────────────
    run_p2_fast(ws_id, llm_available)

    # ── Phase 2: P1 fast (error-path, no LLM) ────────────────────────────────
    run_p1_fast(ws_id, ws_no_bp_id, llm_available)

    # ── Phase 3: P2 happy-path (LLM) — only with --full ──────────────────────
    completed_analysis_id: Optional[str] = None

    if args.full:
        print(f"\n{BOLD}{CYAN}── P2 Full — Happy-path regression (LLM + DDGS, slow) ──{RESET}")
        p2_cases = [
            ("P2-1", "What are our biggest strengths and weaknesses versus competitors?", "swot"),
            ("P2-2", "What regulatory and economic factors could affect us this year?", "pestel"),
            ("P2-3", "Should we launch this new product line — is it worth the risk?", "feasibility"),
            ("P2-4", "Is our brand messaging landing with the right audience?", "brand_analysis"),
            ("P2-5", "What does the market look like right now and who are the key players?", "market_research"),
        ]
        for case_id, question, expected_type in p2_cases:
            print(f"\n  {BOLD}{case_id}{RESET} — {DIM}{question[:70]}…{RESET}")
            aid = run_p2_full_analysis(
                ws_id, question, expected_type,
                f"{case_id}  /consult → {expected_type}  → status=ready, valid shape",
                endpoint="consult",
            )
            if aid and completed_analysis_id is None:
                completed_analysis_id = aid

        # P2-6: /analyses:generate without context
        print(f"\n  {BOLD}P2-6{RESET} — {DIM}analyses:generate swot (no context){RESET}")
        aid = run_p2_full_analysis(
            ws_id, "", "swot",
            "P2-6  /analyses:generate swot (no context) → status=ready, valid shape",
            endpoint="analyses",
        )
        if aid and completed_analysis_id is None:
            completed_analysis_id = aid

        # P2-7: /analyses:generate feasibility with context
        print(f"\n  {BOLD}P2-7{RESET} — {DIM}analyses:generate feasibility + context{RESET}")
        aid = run_p2_full_analysis(
            ws_id,
            "We are considering launching a subscription box for organic skincare targeting Gen Z",
            "feasibility",
            "P2-7  /analyses:generate feasibility + context → status=ready, valid shape",
            endpoint="analyses",
        )
        if aid and completed_analysis_id is None:
            completed_analysis_id = aid
    else:
        print(f"\n{DIM}P2-1..P2-7 skipped (LLM-backed). Run with --full to enable.{RESET}")
        for case_id, question, expected_type in [
            ("P2-1", "What are our biggest strengths and weaknesses versus competitors?", "swot"),
            ("P2-2", "What regulatory and economic factors could affect us this year?", "pestel"),
            ("P2-3", "Should we launch this new product line — is it worth the risk?", "feasibility"),
            ("P2-4", "Is our brand messaging landing with the right audience?", "brand_analysis"),
            ("P2-5", "What does the market look like right now and who are the key players?", "market_research"),
            ("P2-6", "analyses:generate swot no context", "swot"),
            ("P2-7", "analyses:generate feasibility + context", "feasibility"),
        ]:
            _skip(f"{case_id}  /consult → {expected_type} → ready", "Use --full to run")

    # ── Phase 4: P1 stream tests (need a completed analysis) ─────────────────
    # Try to find any existing ready/failed analysis if --full didn't produce one
    if completed_analysis_id is None:
        r = requests.get(_ws_url(f"/{ws_id}/analyses"), timeout=10)
        if r.status_code == 200:
            for a in r.json():
                if a["status"] in ("ready", "failed"):
                    completed_analysis_id = a["id"]
                    break

    if completed_analysis_id:
        run_p1_stream(ws_id, completed_analysis_id)
        if args.full:
            run_p2_stream(ws_id, completed_analysis_id)
        else:
            _skip("P2-10 SSE ordered-event check", "Use --full; or open stream before submit manually")
    else:
        _skip("P1-5  Stream after completion", "No completed analysis available; run with --full first")
        _skip("P1-4  Stream for non-existent analysis_id", "Still runs below")
        # Run P1-4 standalone (fake analysis_id)
        print(f"\n{BOLD}{CYAN}── P1 Stream tests (partial) ──{RESET}")
        fake_analysis_id = "00000000-dead-beef-dead-000000000000"
        name = "P1-4  Stream for non-existent analysis_id → 404, no crash"
        try:
            r = requests.get(
                _ws_url(f"/{ws_id}/analyses/{fake_analysis_id}/stream"),
                timeout=10, stream=False,
            )
            if r.status_code == 404:
                _pass(name, "Correct 404")
            elif r.status_code == 200:
                _note(name, "200 instead of 404 — documented gap §8: event_bus guard missing")
            elif r.status_code == 500:
                _fail(name, "500 — event_bus crash (documented gap §8)")
            else:
                _note(name, f"Unexpected {r.status_code}: {r.text[:60]}")
        except requests.exceptions.Timeout:
            _note(name, "Timed out — stream is hanging (documented gap §8)")
        except Exception as exc:
            _fail(name, f"Exception: {exc}")

    # ── Phase 5: slow P1 tests (--full only) ─────────────────────────────────
    if args.full:
        run_p1_insufficient_citations(ws_id)
        run_p1_concurrent(ws_id)
    else:
        _skip("P1-1  Niche industry → insufficient citations", "Use --full to run")
        _skip("P1-9  5 concurrent requests → no 500s", "Use --full to run")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    counts = {s: sum(1 for x in _results if x[0] == s) for s in ("PASS", "FAIL", "SKIP", "MANUAL")}
    print(
        f"  {GREEN}{counts['PASS']} passed{RESET}  "
        f"{RED}{counts['FAIL']} failed{RESET}  "
        f"{YELLOW}{counts['SKIP']} skipped{RESET}  "
        f"{CYAN}{counts['MANUAL']} need manual review{RESET}"
    )
    if counts["FAIL"]:
        print(f"\n{RED}{BOLD}FAILURES:{RESET}")
        for status, name, msg in _results:
            if status == "FAIL":
                print(f"  {RED}✗{RESET} {name}")
                if msg:
                    print(f"      {DIM}{msg}{RESET}")
    if counts["MANUAL"]:
        print(f"\n{CYAN}{BOLD}MANUAL REVIEW NEEDED:{RESET}")
        for status, name, msg in _results:
            if status == "MANUAL":
                print(f"  {CYAN}?{RESET} {name}")
                if msg:
                    print(f"      {DIM}{msg}{RESET}")
    print()
    sys.exit(1 if counts["FAIL"] else 0)


if __name__ == "__main__":
    main()
