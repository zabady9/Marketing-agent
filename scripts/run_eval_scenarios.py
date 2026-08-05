#!/usr/bin/env python3
"""
Eval harness for consult-eval-scenarios.md  (A1–F2).

Sections A, D, E : raw capture only — logs request, classification, status, output/eval.
Sections B, C, F : flags obvious deviations from Expected.

Usage:
  python scripts/run_eval_scenarios.py [--ws-id ID] [--base-url URL] [--out FILE]
"""

import argparse
import json
import os
import sys
import threading
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

# ── config ─────────────────────────────────────────────────────────────────────

BASE_URL   = "http://localhost:8001"
WS_ID      = None          # set by --ws-id or auto-detected
OUT_FILE   = None          # set by --out; defaults to my_claude_utils/eval-run.json

# Per-scenario poll timeout (seconds). Most analyses finish in 120-180 s.
POLL_TIMEOUT   = 300
# Timeout for the initial POST that triggers a consult (includes LLM classification).
CONSULT_TIMEOUT = 120
# B1 run count
B1_RUNS = 7

# ── state ──────────────────────────────────────────────────────────────────────

_log_lock = threading.Lock()
_entries: list[dict] = []          # all captured scenario entries


# ── http helpers ───────────────────────────────────────────────────────────────

def _ws(path: str) -> str:
    return f"{BASE_URL}/api/workspaces{path}"


def _post(path: str, payload: dict, timeout: int = CONSULT_TIMEOUT) -> requests.Response:
    return requests.post(_ws(path), json=payload, timeout=timeout)


def _get(path: str, timeout: int = 30) -> requests.Response:
    return requests.get(_ws(path), timeout=timeout)


def _poll(ws_id: str, analysis_id: str, timeout: int = POLL_TIMEOUT) -> Optional[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = _get(f"/{ws_id}/analyses/{analysis_id}", timeout=15)
            if r.status_code != 200:
                return None
            body = r.json()
            if body["status"] != "generating":
                return body
        except Exception:
            pass
        time.sleep(5)
    return None


def _read_sse(ws_id: str, analysis_id: str, max_events: int = 30,
              timeout: int = 20) -> list[dict]:
    url = _ws(f"/{ws_id}/analyses/{analysis_id}/stream")
    events = []
    try:
        with requests.get(url, stream=True, timeout=timeout) as resp:
            for raw in resp.iter_lines(decode_unicode=True):
                if raw and raw.startswith("data: "):
                    try:
                        evt = json.loads(raw[6:])
                        events.append(evt)
                        if evt.get("type") in ("done", "error"):
                            break
                        if len(events) >= max_events:
                            break
                    except json.JSONDecodeError:
                        pass
    except Exception as exc:
        events.append({"_error": str(exc)})
    return events


# ── workspace helpers ───────────────────────────────────────────────────────────

def _create_ws(name: str) -> Optional[str]:
    try:
        r = requests.post(f"{BASE_URL}/api/workspaces", json={"name": name}, timeout=20)
        if r.status_code in (200, 201):
            return r.json()["id"]
    except Exception:
        pass
    return None


def _set_bp(ws_id: str, **fields) -> bool:
    defaults = {"brand_name": "TestBrand", "company_name": "TestCo"}
    defaults.update(fields)
    try:
        r = requests.put(_ws(f"/{ws_id}/brand-profile"), json=defaults, timeout=20)
        return r.status_code in (200, 201)
    except Exception:
        return False


def _auto_ws() -> Optional[str]:
    try:
        r = requests.get(f"{BASE_URL}/api/workspaces", timeout=20)
        if r.status_code != 200:
            return None
        for ws in r.json():
            bp = requests.get(_ws(f"/{ws['id']}/brand-profile"), timeout=10)
            if bp.status_code == 200 and bp.json().get("brand_name"):
                return ws["id"]
    except Exception:
        pass
    return None


# ── entry builder / logger ─────────────────────────────────────────────────────

def _record(scenario: str, section: str,
            request_method: str, request_url: str, request_body: Optional[dict],
            http_status: int, response_body,
            final_status: Optional[str] = None,
            classified_as: Optional[str] = None,
            output: Optional[dict] = None,
            eval_obj: Optional[dict] = None,
            citations: Optional[list] = None,
            error_msg: Optional[str] = None,
            flags: Optional[list[str]] = None,
            extra: Optional[dict] = None) -> dict:
    entry = {
        "scenario": scenario,
        "section": section,
        "request": {
            "method": request_method,
            "url": request_url,
            "body": request_body,
        },
        "initial_http_status": http_status,
        "response_body": response_body,
        "classified_as": classified_as,
        "final_status": final_status,
        "output": output,
        "eval": eval_obj,
        "citations_count": len(citations) if citations is not None else None,
        "citations": citations,
        "error_msg": error_msg,
        "flags": flags or [],
        "extra": extra or {},
    }
    with _log_lock:
        _entries.append(entry)
    return entry


def _print_entry(e: dict) -> None:
    print(f"\n{'─'*70}")
    print(f"  {e['scenario']}  [{e.get('section','')}]")
    req = e.get("request") or {}
    if req.get("method") and req.get("url"):
        print(f"  {req['method']} {req['url']}")
    if req.get("body"):
        q = req["body"].get("question") or req["body"].get("context", "")
        if q:
            print(f"  input    : {q[:120]!r}")
    print(f"  http     : {e['initial_http_status']}")
    if e["classified_as"]:
        print(f"  classified_as: {e['classified_as']!r}")
    if e["final_status"]:
        print(f"  final    : {e['final_status']}")
    if e["eval"]:
        ev = e["eval"]
        print(f"  eval     : passed={ev.get('passed')}  overall={ev.get('overall_score')}")
        scores = {k: v for k, v in ev.items() if k not in ("passed","overall_score","summary")}
        if scores:
            print(f"           : {scores}")
    if e["error_msg"]:
        print(f"  error    : {e['error_msg']!r}")
    if e["flags"]:
        for f in e["flags"]:
            print(f"  ⚠ FLAG   : {f}")
    if e["extra"]:
        print(f"  extra    : {e['extra']}")


# ── scenario runners ──────────────────────────────────────────────────────────

def _run_consult(ws_id: str, scenario: str, section: str, question: str,
                 expected_http: int = 202,
                 expected_classification: Optional[str] = None,
                 wait_complete: bool = True) -> dict:
    """
    POST /consult, optionally poll to completion.
    Returns the recorded entry.
    """
    url = f"/{ws_id}/consult"
    payload = {"question": question}
    flags = []

    try:
        r = _post(url, payload)
        resp_body = None
        try:
            resp_body = r.json()
        except Exception:
            resp_body = {"_raw": r.text[:2000]}

        classified_as = None
        analysis_id = None

        if r.status_code == 202:
            classified_as = resp_body.get("classified_as")
            analysis_id = resp_body.get("id")
        elif r.status_code == 422:
            detail = resp_body.get("detail", {})
            if isinstance(detail, dict):
                classified_as = detail.get("classification")

        # Section B/C/F — check expected
        if section in ("B", "C", "F"):
            if r.status_code != expected_http:
                flags.append(f"Expected HTTP {expected_http}, got {r.status_code}")
            if expected_classification and classified_as != expected_classification:
                flags.append(
                    f"Expected classification={expected_classification!r}, "
                    f"got {classified_as!r}"
                )

        if r.status_code != 202 or not wait_complete or not analysis_id:
            return _record(
                scenario, section, "POST", _ws(url), payload,
                r.status_code, resp_body,
                classified_as=classified_as,
                flags=flags,
            )

        # Poll to completion
        final = _poll(ws_id, analysis_id)
        if final is None:
            flags.append("Timed out waiting for analysis completion")
            return _record(
                scenario, section, "POST", _ws(url), payload,
                r.status_code, resp_body,
                classified_as=classified_as,
                final_status="timeout",
                flags=flags,
            )

        results = final.get("results") or {}
        return _record(
            scenario, section, "POST", _ws(url), payload,
            r.status_code, resp_body,
            classified_as=classified_as,
            final_status=final["status"],
            output=results.get("output"),
            eval_obj=results.get("eval"),
            citations=results.get("citations"),
            error_msg=final.get("error"),
            flags=flags,
            extra={"analysis_id": analysis_id, "disclaimer": results.get("disclaimer", "")[:200]},
        )

    except requests.exceptions.Timeout:
        return _record(
            scenario, section, "POST", _ws(url), payload,
            -1, {"_error": "Request timed out"},
            flags=flags + ["Request timed out"],
        )
    except Exception as exc:
        return _record(
            scenario, section, "POST", _ws(url), payload,
            -1, {"_error": str(exc)},
            flags=flags + [f"Exception: {exc}"],
        )


def _run_generate(ws_id: str, scenario: str, section: str,
                  analysis_type: str, context: Optional[str] = None,
                  wait_complete: bool = True) -> dict:
    """POST /analyses:generate, optionally poll to completion."""
    url = f"/{ws_id}/analyses:generate"
    payload: dict = {"analysis_type": analysis_type}
    if context is not None:
        payload["context"] = context
    flags = []

    try:
        r = _post(url, payload, timeout=30)
        resp_body = None
        try:
            resp_body = r.json()
        except Exception:
            resp_body = {"_raw": r.text[:2000]}

        if r.status_code != 202 or not wait_complete:
            return _record(
                scenario, section, "POST", _ws(url), payload,
                r.status_code, resp_body,
                flags=flags,
            )

        analysis_id = resp_body.get("id")
        if not analysis_id:
            return _record(
                scenario, section, "POST", _ws(url), payload,
                r.status_code, resp_body,
                flags=["No analysis_id in 202 response"],
            )

        final = _poll(ws_id, analysis_id)
        if final is None:
            flags.append("Timed out waiting for analysis completion")
            return _record(
                scenario, section, "POST", _ws(url), payload,
                r.status_code, resp_body,
                final_status="timeout",
                flags=flags,
            )

        results = final.get("results") or {}
        return _record(
            scenario, section, "POST", _ws(url), payload,
            r.status_code, resp_body,
            final_status=final["status"],
            output=results.get("output"),
            eval_obj=results.get("eval"),
            citations=results.get("citations"),
            error_msg=final.get("error"),
            flags=flags,
            extra={"analysis_id": analysis_id, "disclaimer": results.get("disclaimer", "")[:200]},
        )

    except requests.exceptions.Timeout:
        return _record(
            scenario, section, "POST", _ws(url), payload,
            -1, {"_error": "Request timed out"},
            flags=["Request timed out"],
        )
    except Exception as exc:
        return _record(
            scenario, section, "POST", _ws(url), payload,
            -1, {"_error": str(exc)},
            flags=[f"Exception: {exc}"],
        )


# ── section runners ────────────────────────────────────────────────────────────

def run_section_A(ws_id: str) -> list[dict]:
    print("\n\n══ Section A — Happy-path routing + output quality ══")
    cases = [
        ("A1", "swot",            "What are my brand's biggest weaknesses vs competitors?"),
        ("A2", "pestel",          "How will new e-invoicing regulations affect our operations?"),
        ("A3", "feasibility",     "Should we launch a premium product line in Riyadh?"),
        ("A4", "brand_analysis",  "Is our messaging consistent with how our target audience sees us?"),
        ("A5", "market_research", "What does the competitive landscape look like for our industry right now?"),
    ]

    results = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {
            ex.submit(_run_consult, ws_id, sid, "A", q, 202, expected_cls, True): sid
            for sid, expected_cls, q in cases
        }
        for fut in as_completed(futures):
            sid = futures[fut]
            entry = fut.result()
            results[sid] = entry
            _print_entry(entry)

    return list(results.values())


def run_section_B(ws_id: str) -> list[dict]:
    print("\n\n══ Section B — Classification boundary cases ══")
    entries = []

    # B1: run B1_RUNS times, record each outcome
    print(f"\n  B1 — 'Tell me about the market and our competition' × {B1_RUNS} runs")
    b1_outcomes = []
    for i in range(B1_RUNS):
        e = _run_consult(ws_id, f"B1-run{i+1}", "B",
                         "Tell me about the market and our competition.",
                         expected_http=422,
                         expected_classification="general",
                         wait_complete=False)
        b1_outcomes.append(e)
        outcome = f"http={e['initial_http_status']} cls={e['classified_as']!r}"
        print(f"    run {i+1}: {outcome}")

    # Summarise B1
    http_202 = sum(1 for e in b1_outcomes if e["initial_http_status"] == 202)
    http_422 = sum(1 for e in b1_outcomes if e["initial_http_status"] == 422)
    cls_counts: dict = {}
    for e in b1_outcomes:
        cls = e["classified_as"] or "(none)"
        cls_counts[cls] = cls_counts.get(cls, 0) + 1
    summary = {
        "total_runs": B1_RUNS,
        "http_202_count": http_202,
        "http_422_count": http_422,
        "classification_distribution": cls_counts,
        "leakage_rate_pct": round(100.0 * http_202 / B1_RUNS, 1),
    }
    print(f"  B1 summary: {summary}")
    b1_summary_entry = {
        "scenario": "B1-summary",
        "section": "B",
        "request": {"body": {"question": "Tell me about the market and our competition."}},
        "flags": [f"Leakage: {http_202}/{B1_RUNS} runs returned 202 (chose a specific type instead of 'general')"]
                 if http_202 > 0 else [],
        "extra": {"b1_summary": summary, "individual_runs": b1_outcomes},
    }
    with _log_lock:
        _entries.append(b1_summary_entry)
    entries.extend(b1_outcomes)
    entries.append(b1_summary_entry)

    # B2–B6 in parallel (classification-only, no full analysis)
    bc_cases = [
        ("B2", 422, "general",      "Tell me everything about my business"),
        ("B3", 422, "out_of_scope", "Can you write me a LinkedIn post?"),
        ("B4", 422, "out_of_scope", "What's a good subject line for our next newsletter?"),
        ("B5", 422, "out_of_scope", "Should we give our new hires a signing bonus?"),
        ("B6", None, None,          "Give me a SWOT and also tell me about the macro environment."),
    ]

    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {
            ex.submit(_run_consult, ws_id, sid, "B", q, exp_http, exp_cls, False): sid
            for sid, exp_http, exp_cls, q in bc_cases
        }
        for fut in as_completed(futures):
            sid = futures[fut]
            e = fut.result()
            # B2: check clarifying message is specific, not generic
            if sid == "B2" and e["initial_http_status"] == 422:
                detail = (e.get("response_body") or {}).get("detail", {})
                msg = detail.get("message", "") if isinstance(detail, dict) else ""
                # Specific clarifying message should mention analysis types
                type_hints = ["swot","pestel","feasibility","brand","market","competitive","regulatory"]
                if not any(h in msg.lower() for h in type_hints):
                    e["flags"].append(
                        f"B2 clarifying message may be generic (no analysis-type keywords found): {msg[:150]!r}"
                    )
            # B3: check no 'id' in response
            if sid == "B3":
                resp = e.get("response_body") or {}
                if "id" in resp:
                    e["flags"].append("B3: 'id' found in out_of_scope response body — spec says no id")
                detail = resp.get("detail", {})
                msg = (detail.get("message", "") if isinstance(detail, dict) else str(detail))
                if "sorry" in msg.lower() or "apologize" in msg.lower():
                    e["flags"].append(f"B3: decline message apologizes excessively: {msg[:120]!r}")
            # B6: just note the chosen type
            if sid == "B6":
                chosen = e.get("classified_as")
                if chosen:
                    e["flags"].append(
                        f"B6: classifier chose {chosen!r} for dual-type question — "
                        "check if response acknowledges partial coverage"
                    )
            entries.append(e)
            _print_entry(e)

    return entries


def run_section_C(ws_id: str, thin_bp_ws_id: Optional[str]) -> list[dict]:
    print("\n\n══ Section C — Input robustness / malformed input ══")
    entries = []

    # C1-C5: classification tests (may or may not wait for completion)
    # C1 empty, C2 whitespace
    for sid, q, label in [("C1", "", "empty string"), ("C2", "   ", "whitespace-only")]:
        e = _run_consult(ws_id, sid, "C", q, wait_complete=False)
        # Neither should produce a fabricated analysis — flag 202 as notable
        if e["initial_http_status"] == 202:
            e["flags"].append(
                f"C1/C2: empty/whitespace question accepted (202, classified={e['classified_as']!r}) "
                "— fabricated analysis risk if it runs to completion"
            )
        elif e["initial_http_status"] not in (422,):
            e["flags"].append(f"Unexpected status {e['initial_http_status']} for {label!r} input")
        entries.append(e)
        _print_entry(e)

    # C3: extremely long question (600+ chars, important detail in back half)
    front_padding = (
        "We are a growing company in a competitive market and we want to understand "
        "the strategic landscape better and evaluate our position. We've been thinking "
        "about many different things and want a comprehensive analysis. " * 3
    )
    specific_tail = (
        "IMPORTANT_DETAIL_AFTER_250_CHARS: The real question is whether we should "
        "pivot from B2B to direct-to-consumer specifically in the UAE luxury segment, "
        "targeting women 25-40 with household income above AED 40,000/month. This pivot "
        "would require abandoning our existing 12 enterprise contracts worth $2.4M ARR. "
        "Please focus the analysis on this specific pivot decision."
    )
    long_q = front_padding + specific_tail
    print(f"\n  C3 long question: {len(long_q)} chars, specific detail starts at char ~{len(front_padding)}")
    e_c3 = _run_consult(ws_id, "C3", "C", long_q, wait_complete=True)
    # Check if the tail-detail (UAE luxury, D2C pivot) appears in output
    if e_c3["output"]:
        out_str = json.dumps(e_c3["output"]).lower()
        tail_keywords = ["uae", "luxury", "d2c", "direct-to-consumer", "pivot", "enterprise contracts"]
        found = [k for k in tail_keywords if k in out_str]
        if not found:
            e_c3["flags"].append(
                "C3 TRUNCATION EFFECT: None of the specific tail-detail keywords found in output "
                f"({tail_keywords}) — suggests truncation silently dropped the real question. "
                f"Output snippet: {out_str[:300]}"
            )
        else:
            e_c3["extra"]["c3_tail_keywords_found"] = found
    entries.append(e_c3)
    _print_entry(e_c3)

    # C4, C5 parallel (Arabic)
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {
            ex.submit(
                _run_consult, ws_id, "C4", "C",
                "ما هي التهديدات التنافسية الأساسية التي تواجه شركتنا؟",
                202, "swot", False
            ): "C4",
            ex.submit(
                _run_consult, ws_id, "C5", "C",
                "ما هو تحليل SWOT المناسب لعلامتنا التجارية في السوق السعودي؟",
                202, "swot", False
            ): "C5",
        }
        for fut in as_completed(futures):
            sid = futures[fut]
            e = fut.result()
            if e["initial_http_status"] == 500:
                e["flags"].append(f"{sid}: 500 on Arabic input — possible encoding/crash bug")
            entries.append(e)
            _print_entry(e)

    # C6: thin brand profile
    if not thin_bp_ws_id:
        placeholder = {
            "scenario": "C6", "section": "C",
            "flags": ["SKIPPED — no thin-brand-profile workspace available"],
            "request": {}, "initial_http_status": 0, "response_body": None,
        }
        with _log_lock:
            _entries.append(placeholder)
        entries.append(placeholder)
        print("\n  C6: SKIPPED — thin-brand-profile workspace not available")
    else:
        print(f"\n  C6 thin brand profile workspace: {thin_bp_ws_id}")
        e_c6 = _run_consult(thin_bp_ws_id, "C6", "C",
                             "What are our biggest weaknesses compared to competitors?",
                             wait_complete=True)
        if e_c6["output"]:
            out_str = json.dumps(e_c6["output"])
            # Thin profile: check for generic/brand-agnostic output
            e_c6["extra"]["c6_note"] = (
                "Manually review: does output read as generic (interchangeable with any brand), "
                "or does it use brand-name-specific unsupported claims?"
            )
        entries.append(e_c6)
        _print_entry(e_c6)

    return entries


def run_section_D(ws_id: str) -> list[dict]:
    print("\n\n══ Section D — /analyses:generate classification bypass ══")
    cases = [
        ("D1", "pestel",         "We're deciding whether to give our new hires a signing bonus."),
        ("D2", "market_research", "What should I name my cat?"),
    ]
    results = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {
            ex.submit(_run_generate, ws_id, sid, "D", atype, ctx, True): sid
            for sid, atype, ctx in cases
        }
        for fut in as_completed(futures):
            sid = futures[fut]
            entry = fut.result()
            results[sid] = entry
            # Add a reminder for manual review
            entry["extra"]["manual_review"] = (
                f"{sid}: inspect output quality — does it fill sections with generic filler, "
                "or fabricate a strained connection to make the mismatch look intentional?"
            )
            _print_entry(entry)

    return list(results.values())


def run_section_E(ws_id: str, completed_analysis_id: Optional[str]) -> list[dict]:
    print("\n\n══ Section E — Rubric stress tests ══")
    entries = []

    # E1: niche industry → insufficient citations
    print("\n  E1 — Niche industry workspace (insufficient citations test)")
    niche_ws = _create_ws("eval-e1-niche")
    if niche_ws:
        ok = _set_bp(niche_ws,
                     industry="bespoke hand-painted bismuth crystal jewelry for antique collectors",
                     brand_name="CrystalBismuth Atelier")
        if ok:
            e_e1 = _run_generate(niche_ws, "E1", "E", "market_research", wait_complete=True)
            if e_e1["final_status"] == "failed":
                err = e_e1.get("error_msg", "")
                if "Insufficient sources found" in err:
                    e_e1["extra"]["e1_result"] = "EXPECTED: failed with Insufficient sources"
                else:
                    e_e1["flags"].append(f"E1: failed but error message doesn't match spec: {err!r}")
            elif e_e1["final_status"] == "ready":
                e_e1["extra"]["e1_result"] = (
                    "DDGS returned ≥4 results — test inconclusive (can't force < citations with this industry). "
                    f"citations_count={e_e1['citations_count']}"
                )
                if e_e1.get("eval_obj"):
                    csr = e_e1["eval_obj"].get("citation_support_rate")
                    e_e1["extra"]["e1_csr"] = csr
                    if csr is not None and csr < 0.8:
                        e_e1["flags"].append(
                            f"E1: citation_support_rate={csr} < 0.80 even though completed — "
                            "sparse sources causing over-citation?"
                        )
        else:
            e_e1 = {"scenario": "E1", "section": "E",
                    "flags": ["Could not set brand profile on niche workspace"],
                    "request": {}, "initial_http_status": 0, "response_body": None}
    else:
        e_e1 = {"scenario": "E1", "section": "E",
                "flags": ["Could not create niche workspace"],
                "request": {}, "initial_http_status": 0, "response_body": None}
    entries.append(e_e1)
    _print_entry(e_e1)
    with _log_lock:
        _entries.append(e_e1)

    # E2: concurrent load — 5 requests against different workspaces
    print("\n  E2 — 5 concurrent /consult requests (different workspaces)")
    # Create 5 temp workspaces + brand profiles
    concurrent_ws_ids = []
    for i in range(5):
        cws = _create_ws(f"eval-e2-concurrent-{i}")
        if cws and _set_bp(cws, industry="saas technology", brand_name=f"ConcurrentBrand{i}"):
            concurrent_ws_ids.append(cws)

    if len(concurrent_ws_ids) < 3:
        # Fall back to reusing the main workspace
        concurrent_ws_ids = [ws_id] * 5

    e2_entries = []
    e2_lock = threading.Lock()

    def _e2_one(i: int, cws_id: str) -> dict:
        return _run_consult(
            cws_id, f"E2-req{i+1}", "E",
            f"What does the competitive landscape look like for our software industry?",
            wait_complete=True,
        )

    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(_e2_one, i, concurrent_ws_ids[i % len(concurrent_ws_ids)]): i
                   for i in range(5)}
        for fut in as_completed(futures):
            i = futures[fut]
            e = fut.result()
            e2_entries.append(e)
            print(f"    E2 req {i+1}: status={e['final_status']}  "
                  f"http={e['initial_http_status']}  "
                  f"flags={e['flags']}")

    # Summarise E2
    e2_ready    = sum(1 for e in e2_entries if e.get("final_status") == "ready")
    e2_failed   = sum(1 for e in e2_entries if e.get("final_status") == "failed")
    e2_timeout  = sum(1 for e in e2_entries if e.get("final_status") == "timeout")
    e2_summary = {
        "total": len(e2_entries),
        "ready": e2_ready,
        "failed": e2_failed,
        "timeout": e2_timeout,
        "note": (
            "DDGS throttling may inflate failure count under concurrency (§E2). "
            "Compare failure rate here vs sequential runs to isolate infra vs LLM failures."
        ),
    }
    print(f"  E2 summary: {e2_summary}")
    e2_summary_entry = {
        "scenario": "E2-summary", "section": "E",
        "extra": {"e2_summary": e2_summary, "individual_runs": e2_entries},
        "flags": [],
        "request": {}, "initial_http_status": 0, "response_body": None,
    }
    with _log_lock:
        _entries.append(e2_summary_entry)
    entries.extend(e2_entries)
    entries.append(e2_summary_entry)

    # E3: feasibility — saturated/regulated market (should produce do_not_proceed or proceed_with_caution)
    print("\n  E3 — Feasibility in saturated/regulated market")
    e_e3 = _run_consult(
        ws_id, "E3", "E",
        "Should we launch a new ride-hailing app to compete directly with Uber and Careem "
        "in Saudi Arabia given the current regulatory environment and market saturation?",
        wait_complete=True,
    )
    if e_e3["output"] and e_e3["final_status"] == "ready":
        rec = e_e3["output"].get("recommendation")
        risks = e_e3["output"].get("key_risks")
        rationale = e_e3["output"].get("recommendation_rationale", "")
        e_e3["extra"]["e3_recommendation"] = rec
        e_e3["extra"]["e3_key_risks_present"] = bool(risks)
        if rec == "proceed":
            e_e3["flags"].append(
                f"E3 RC FLAG: recommendation=proceed for a saturated/regulated market question — "
                f"check if key_risks contradict this. key_risks snippet: "
                f"{json.dumps(risks)[:300] if risks else 'none'}"
            )
        elif rec in ("proceed_with_caution", "do_not_proceed"):
            e_e3["extra"]["e3_result"] = f"EXPECTED direction: {rec}"
    entries.append(e_e3)
    _print_entry(e_e3)

    # E4: eval non-determinism — re-run eval agent 3x on same completed analysis
    print("\n  E4 — Eval non-determinism (3 re-runs of eval agent on same analysis)")
    if not completed_analysis_id:
        # Try to find one from already-run analyses
        try:
            r = requests.get(_ws(f"/{ws_id}/analyses"), timeout=20)
            if r.status_code == 200:
                for a in r.json():
                    if a["status"] == "ready" and a.get("results"):
                        completed_analysis_id = a["id"]
                        break
        except Exception:
            pass

    if not completed_analysis_id:
        e_e4 = {"scenario": "E4", "section": "E",
                "flags": ["SKIPPED — no completed analysis available for re-eval"],
                "request": {}, "initial_http_status": 0, "response_body": None}
        entries.append(e_e4)
        with _log_lock:
            _entries.append(e_e4)
        print("  E4: SKIPPED — no completed analysis")
    else:
        print(f"    E4 target analysis_id: {completed_analysis_id}")
        eval_results = []
        url = f"/{ws_id}/analyses/{completed_analysis_id}:evaluate"
        for run_i in range(3):
            try:
                r = requests.post(_ws(url), timeout=120)
                if r.status_code == 200:
                    body = r.json()
                    ev = (body.get("results") or {}).get("eval", {})
                    eval_results.append(ev)
                    print(f"    E4 run {run_i+1}: overall_score={ev.get('overall_score')}  "
                          f"passed={ev.get('passed')}")
                else:
                    eval_results.append({"_error": f"HTTP {r.status_code}: {r.text[:100]}"})
            except Exception as exc:
                eval_results.append({"_error": str(exc)})

        # Compute spread
        scores = [e.get("overall_score") for e in eval_results if isinstance(e.get("overall_score"), (int,float))]
        spread = (max(scores) - min(scores)) if len(scores) >= 2 else None
        flags = []
        if spread is not None and spread > 0.10:
            flags.append(
                f"E4 SPREAD WARNING: overall_score range = {min(scores):.3f}–{max(scores):.3f} "
                f"(spread={spread:.3f}) — wide enough to flip 'passed' near the 0.75 threshold"
            )

        e_e4 = {
            "scenario": "E4", "section": "E",
            "extra": {
                "analysis_id": completed_analysis_id,
                "eval_runs": eval_results,
                "score_spread": spread,
            },
            "flags": flags,
            "request": {"method": "POST", "url": _ws(url), "body": None},
            "initial_http_status": 200,
            "response_body": None,
        }
        with _log_lock:
            _entries.append(e_e4)
        entries.append(e_e4)
        _print_entry(e_e4)

    return entries


def run_section_F(ws_id: str, completed_analysis_id: Optional[str]) -> list[dict]:
    print("\n\n══ Section F — Infra / API-contract edge cases ══")
    entries = []

    # F1: SSE stream against non-existent analysis_id
    fake_id = "00000000-dead-beef-dead-000000000000"
    f1_url = f"/{ws_id}/analyses/{fake_id}/stream"
    print(f"\n  F1 — SSE stream for non-existent analysis_id")
    flags_f1 = []
    try:
        r = requests.get(_ws(f1_url), timeout=10, stream=False)
        if r.status_code == 404:
            flags_f1 = []  # expected per spec
        elif r.status_code == 200:
            flags_f1.append(
                "F1 DOCUMENTED BUG: returned 200 instead of 404 for non-existent analysis_id "
                "(event_bus.exists() guard missing per §4.4)"
            )
        elif r.status_code == 500:
            flags_f1.append("F1: 500 — event_bus crash on non-existent id")
        else:
            flags_f1.append(f"F1: unexpected status {r.status_code}")

        e_f1 = _record("F1", "F", "GET", _ws(f1_url), None,
                       r.status_code, {"status_code": r.status_code, "body": r.text[:200]},
                       flags=flags_f1)
    except requests.exceptions.Timeout:
        e_f1 = _record("F1", "F", "GET", _ws(f1_url), None,
                       -1, {"_error": "timed out"},
                       flags=["F1 DOCUMENTED BUG: stream hangs instead of returning 404 "
                              "(event_bus guard missing per §4.4)"])

    entries.append(e_f1)
    _print_entry(e_f1)

    # F2: SSE stream opened after completion → immediate done event
    print(f"\n  F2 — SSE stream opened after completion")
    if not completed_analysis_id:
        e_f2 = {"scenario": "F2", "section": "F",
                "flags": ["SKIPPED — no completed analysis available"],
                "request": {}, "initial_http_status": 0, "response_body": None}
        entries.append(e_f2)
        with _log_lock:
            _entries.append(e_f2)
        print("  F2: SKIPPED — no completed analysis")
    else:
        f2_url = f"/{ws_id}/analyses/{completed_analysis_id}/stream"
        flags_f2 = []
        events = _read_sse(ws_id, completed_analysis_id, timeout=15)
        if not events:
            flags_f2.append("F2: No events received from stream")
        elif events[0].get("type") not in ("done", "error"):
            flags_f2.append(
                f"F2: First event was {events[0].get('type')!r} instead of done/error — "
                "stale event replay possible"
            )
        if len(events) > 1:
            flags_f2.append(
                f"F2: Received {len(events)} events on completed analysis — "
                "expected exactly 1 immediate done"
            )
        e_f2 = _record("F2", "F", "GET", _ws(f2_url), None,
                       200, {"events": events},
                       flags=flags_f2,
                       extra={"analysis_id": completed_analysis_id, "event_count": len(events)})
        entries.append(e_f2)
        _print_entry(e_f2)

    return entries


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    global BASE_URL, WS_ID, OUT_FILE

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ws-id", default=None,
                        help="Workspace ID with a brand profile already set")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--out", default=None,
                        help="Output JSON file path")
    args = parser.parse_args()

    BASE_URL = args.base_url.rstrip("/")
    OUT_FILE = args.out

    # Auto-detect workspace
    WS_ID = args.ws_id or _auto_ws()
    if not WS_ID:
        print("ERROR: No workspace with a brand profile found. Pass --ws-id.")
        sys.exit(2)

    # Determine output path
    if not OUT_FILE:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(os.path.dirname(script_dir), "my_claude_utils")
        os.makedirs(out_dir, exist_ok=True)
        OUT_FILE = os.path.join(out_dir, "eval-run.json")

    print(f"Eval harness — A1–F2")
    print(f"  server  : {BASE_URL}")
    print(f"  ws_id   : {WS_ID}")
    print(f"  out     : {OUT_FILE}")

    # ── Create thin brand profile workspace for C6 ────────────────────────────
    thin_ws = _create_ws("eval-c6-thin-bp")
    thin_bp_ok = False
    if thin_ws:
        # Set brand profile WITHOUT industry field
        thin_bp_ok = _set_bp(thin_ws, brand_name="ThinBrand", company_name="ThinCo")
        # Patch: also explicitly clear industry by sending empty string
        try:
            requests.put(
                _ws(f"/{thin_ws}/brand-profile"),
                json={"brand_name": "ThinBrand", "company_name": "ThinCo", "industry": ""},
                timeout=20,
            )
        except Exception:
            pass
    thin_bp_ws_id = thin_ws if (thin_ws and thin_bp_ok) else None

    # ── Run all sections ───────────────────────────────────────────────────────
    # A: full analyses (parallel internally)
    a_entries = run_section_A(WS_ID)

    # Find a completed analysis_id from section A for later use
    completed_id = None
    for e in a_entries:
        if e.get("final_status") == "ready" and e.get("extra", {}).get("analysis_id"):
            completed_id = e["extra"]["analysis_id"]
            break

    # B: classification boundary (B1 × N, B2-B6 parallel)
    run_section_B(WS_ID)

    # C: input robustness (C1-C5 parallel, C6 sequential)
    run_section_C(WS_ID, thin_bp_ws_id)

    # D: bypass endpoint (parallel)
    run_section_D(WS_ID)

    # E: rubric stress tests
    run_section_E(WS_ID, completed_id)

    # F: infra edge cases
    run_section_F(WS_ID, completed_id)

    # ── Write results ──────────────────────────────────────────────────────────
    with open(OUT_FILE, "w") as fh:
        json.dump(_entries, fh, indent=2, default=str)

    print(f"\n\n{'═'*70}")
    print(f"  Results written to: {OUT_FILE}")
    total = len(_entries)
    flagged = sum(1 for e in _entries if e.get("flags"))
    print(f"  Total entries: {total}   Entries with flags: {flagged}")
    print()

    # Flags summary
    if flagged:
        print("FLAGGED entries:")
        for e in _entries:
            if e.get("flags"):
                print(f"  [{e['scenario']}]  {e['flags'][0][:100]}")


if __name__ == "__main__":
    main()
