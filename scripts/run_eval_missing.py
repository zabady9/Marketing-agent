#!/usr/bin/env python3
"""
Runs only the missing sections from the first eval-harness run:
  C6  — thin brand profile
  E1  — niche industry / insufficient citations
  E2  — 5 concurrent requests
  E3  — feasibility recommendation consistency
  E4  — eval non-determinism (3 re-runs)
  F1  — SSE stream against non-existent analysis_id
  F2  — SSE stream after completion

Also writes the A-D terminal data (already captured) into the same JSON
so the final file is complete.

Usage:
  python scripts/run_eval_missing.py [--ws-id ID] [--completed-analysis-id ID]
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

BASE_URL  = "http://localhost:8001"
WS_ID     = None
OUT_FILE  = None

_log_lock = threading.Lock()
_entries: list[dict] = []


# ─── http helpers ──────────────────────────────────────────────────────────────

def _ws(path: str) -> str:
    return f"{BASE_URL}/api/workspaces{path}"

def _post(path: str, payload: dict, timeout: int = 120) -> requests.Response:
    return requests.post(_ws(path), json=payload, timeout=timeout)

def _get(path: str, timeout: int = 30) -> requests.Response:
    return requests.get(_ws(path), timeout=timeout)

def _poll(ws_id: str, analysis_id: str, timeout: int = 300) -> Optional[dict]:
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


# ─── record / print ────────────────────────────────────────────────────────────

def _record(scenario, section, method, url, body, http_status, resp_body,
            final_status=None, classified_as=None, output=None, eval_obj=None,
            citations=None, error_msg=None, flags=None, extra=None) -> dict:
    e = {
        "scenario": scenario, "section": section,
        "request": {"method": method, "url": url, "body": body},
        "initial_http_status": http_status, "response_body": resp_body,
        "classified_as": classified_as, "final_status": final_status,
        "output": output, "eval": eval_obj,
        "citations_count": len(citations) if citations is not None else None,
        "citations": citations, "error_msg": error_msg,
        "flags": flags or [], "extra": extra or {},
    }
    with _log_lock:
        _entries.append(e)
    return e

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
    if e.get("classified_as"):
        print(f"  classified_as: {e['classified_as']!r}")
    if e.get("final_status"):
        print(f"  final    : {e['final_status']}")
    if e.get("eval"):
        ev = e["eval"]
        print(f"  eval     : passed={ev.get('passed')}  overall={ev.get('overall_score')}")
        scores = {k: v for k, v in ev.items() if k not in ("passed","overall_score","summary","flags","criteria")}
        if scores:
            print(f"           : {scores}")
    if e.get("error_msg"):
        print(f"  error    : {e['error_msg']!r}")
    for f in e.get("flags", []):
        print(f"  ⚠ FLAG   : {f}")
    if e.get("extra"):
        trimmed = {k: v for k, v in e["extra"].items()
                   if k not in ("disclaimer",) and not isinstance(v, list)}
        if trimmed:
            print(f"  extra    : {trimmed}")


# ─── section C6 ────────────────────────────────────────────────────────────────

def run_c6(ws_id: str) -> None:
    print("\n\n══ C6 — Thin brand profile ══")
    thin_ws = _create_ws("eval-c6-thin-bp-v2")
    if not thin_ws:
        e = {"scenario": "C6", "section": "C",
             "flags": ["SKIPPED — workspace creation failed"],
             "request": {}, "initial_http_status": 0, "response_body": None}
        with _log_lock: _entries.append(e)
        print("  C6: SKIPPED — workspace creation failed")
        return

    ok = _set_bp(thin_ws, brand_name="ThinBrand", company_name="ThinCo", industry="")
    print(f"  thin workspace: {thin_ws}  brand-profile set: {ok}")

    url = f"/{thin_ws}/consult"
    payload = {"question": "What are our biggest weaknesses compared to competitors?"}
    try:
        r = _post(url, payload)
        resp_body = r.json() if r.headers.get("content-type","").startswith("application") else {"_raw": r.text[:500]}
        if r.status_code != 202:
            e = _record("C6", "C", "POST", _ws(url), payload, r.status_code, resp_body,
                        flags=[f"Expected 202, got {r.status_code}"])
            _print_entry(e)
            return

        analysis_id = resp_body.get("id")
        classified_as = resp_body.get("classified_as")
        print(f"  classified_as: {classified_as!r}  polling…")
        final = _poll(thin_ws, analysis_id)
        if not final:
            e = _record("C6", "C", "POST", _ws(url), payload, 202, resp_body,
                        classified_as=classified_as, final_status="timeout",
                        flags=["Timed out"])
        else:
            results = final.get("results") or {}
            out_str = json.dumps(results.get("output", {}))
            tail_keywords = ["competitor", "brand", "market"]
            flags = []
            # Thin profile note
            flags.append(
                "MANUAL REVIEW: does output read as generic (interchangeable with any brand) "
                "or does it make brand-specific claims unsupported by sources?"
            )
            e = _record("C6", "C", "POST", _ws(url), payload, 202, resp_body,
                        classified_as=classified_as,
                        final_status=final["status"],
                        output=results.get("output"),
                        eval_obj=results.get("eval"),
                        citations=results.get("citations"),
                        error_msg=final.get("error"),
                        flags=flags,
                        extra={"analysis_id": analysis_id,
                               "disclaimer": (results.get("disclaimer","")[:200]),
                               "c6_note": "industry='' (thin profile). Check for confident-sounding genericness."})
        _print_entry(e)
    except requests.exceptions.Timeout:
        e = _record("C6", "C", "POST", _ws(url), payload, -1, {"_error":"timeout"},
                    flags=["Request timed out"])
        _print_entry(e)


# ─── section E ─────────────────────────────────────────────────────────────────

def run_e1() -> None:
    print("\n\n══ E1 — Niche industry / insufficient citations ══")
    niche_ws = _create_ws("eval-e1-niche-v2")
    if not niche_ws:
        e = {"scenario": "E1", "section": "E",
             "flags": ["SKIPPED — workspace creation failed"],
             "request": {}, "initial_http_status": 0, "response_body": None}
        with _log_lock: _entries.append(e)
        print("  E1: SKIPPED")
        return

    ok = _set_bp(niche_ws,
                 industry="bespoke hand-painted bismuth crystal jewelry for antique collectors",
                 brand_name="CrystalBismuth Atelier")
    print(f"  niche workspace: {niche_ws}  brand-profile set: {ok}")

    url = f"/{niche_ws}/analyses:generate"
    payload = {"analysis_type": "market_research"}
    try:
        r = _post(url, payload, timeout=30)
        resp_body = r.json()
        if r.status_code != 202:
            e = _record("E1", "E", "POST", _ws(url), payload, r.status_code, resp_body,
                        flags=[f"Expected 202, got {r.status_code}"])
            _print_entry(e)
            return

        analysis_id = resp_body["id"]
        print(f"  analysis_id: {analysis_id}  polling…")
        final = _poll(niche_ws, analysis_id, timeout=180)
        if not final:
            e = _record("E1", "E", "POST", _ws(url), payload, 202, resp_body,
                        final_status="timeout", flags=["Timed out"])
        else:
            results = final.get("results") or {}
            flags = []
            extra = {"analysis_id": analysis_id}
            if final["status"] == "failed":
                err = final.get("error", "")
                if "Insufficient sources found" in err:
                    import re
                    m = re.search(r"Insufficient sources found \((\d+)\)", err)
                    extra["e1_result"] = f"EXPECTED: failed with Insufficient sources (N={m.group(1) if m else '?'})"
                else:
                    flags.append(f"Failed but error doesn't match spec: {err!r}")
            else:
                extra["e1_result"] = (
                    f"DDGS returned enough results — test inconclusive. "
                    f"citations={len(results.get('citations',[]))}"
                )
                ev = results.get("eval") or {}
                csr = ev.get("citation_support_rate") if isinstance(ev, dict) else None
                if csr is None and ev.get("criteria"):
                    for c in ev["criteria"]:
                        if c.get("name") == "citation_support_rate":
                            csr = c.get("score")
                extra["e1_csr"] = csr
                if csr is not None and csr < 0.8:
                    flags.append(f"CSR={csr} < 0.80 on sparse sources — possible over-citation")
            e = _record("E1", "E", "POST", _ws(url), payload, 202, resp_body,
                        final_status=final["status"],
                        output=results.get("output"),
                        eval_obj=results.get("eval"),
                        citations=results.get("citations"),
                        error_msg=final.get("error"),
                        flags=flags, extra=extra)
        _print_entry(e)
    except Exception as exc:
        e = _record("E1", "E", "POST", _ws(url), payload, -1, {"_error": str(exc)},
                    flags=[f"Exception: {exc}"])
        _print_entry(e)


def run_e2(ws_id: str) -> None:
    print("\n\n══ E2 — 5 concurrent /consult requests ══")

    # Create 5 workspaces with brand profiles
    concurrent_ws = []
    for i in range(5):
        cws = _create_ws(f"eval-e2-v2-{i}")
        if cws and _set_bp(cws, industry="saas technology", brand_name=f"ConcurrentBrand{i}"):
            concurrent_ws.append(cws)
    if len(concurrent_ws) < 3:
        concurrent_ws = [ws_id] * 5
    print(f"  using {len(concurrent_ws)} workspaces")

    e2_entries = []

    def _one(i: int, cws_id: str) -> dict:
        url = f"/{cws_id}/consult"
        payload = {"question": "What does the competitive landscape look like for our software industry?"}
        try:
            r = _post(url, payload)
            resp_body = r.json()
            if r.status_code != 202:
                return _record(f"E2-req{i+1}", "E", "POST", _ws(url), payload,
                               r.status_code, resp_body,
                               flags=[f"Expected 202, got {r.status_code}"])
            analysis_id = resp_body.get("id")
            classified_as = resp_body.get("classified_as")
            final = _poll(cws_id, analysis_id)
            if not final:
                return _record(f"E2-req{i+1}", "E", "POST", _ws(url), payload,
                               202, resp_body, classified_as=classified_as,
                               final_status="timeout", flags=["Timed out"])
            results = final.get("results") or {}
            return _record(f"E2-req{i+1}", "E", "POST", _ws(url), payload,
                           202, resp_body,
                           classified_as=classified_as,
                           final_status=final["status"],
                           output=results.get("output"),
                           eval_obj=results.get("eval"),
                           citations=results.get("citations"),
                           error_msg=final.get("error"),
                           extra={"analysis_id": analysis_id, "workspace_id": cws_id})
        except Exception as exc:
            return _record(f"E2-req{i+1}", "E", "POST", _ws(url), payload,
                           -1, {"_error": str(exc)}, flags=[f"Exception: {exc}"])

    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(_one, i, concurrent_ws[i % len(concurrent_ws)]): i for i in range(5)}
        for fut in as_completed(futs):
            i = futs[fut]
            e = fut.result()
            e2_entries.append(e)
            print(f"  req {i+1}: final={e.get('final_status')}  "
                  f"http={e['initial_http_status']}  flags={e.get('flags',[])[0][:60] if e.get('flags') else '-'}")

    ready   = sum(1 for e in e2_entries if e.get("final_status") == "ready")
    failed  = sum(1 for e in e2_entries if e.get("final_status") == "failed")
    timeout = sum(1 for e in e2_entries if e.get("final_status") == "timeout")
    summary = {
        "total": 5, "ready": ready, "failed": failed, "timeout": timeout,
        "note": "DDGS throttling may inflate fail count under concurrency vs sequential.",
    }
    print(f"  summary: {summary}")
    summ_entry = {
        "scenario": "E2-summary", "section": "E",
        "extra": {"e2_summary": summary, "individual_run_ids": [e.get("extra",{}).get("analysis_id") for e in e2_entries]},
        "flags": [], "request": {}, "initial_http_status": 0, "response_body": None,
    }
    with _log_lock:
        _entries.append(summ_entry)


def run_e3(ws_id: str) -> None:
    print("\n\n══ E3 — Feasibility recommendation consistency ══")
    url = f"/{ws_id}/consult"
    payload = {
        "question": (
            "Should we launch a new ride-hailing app to compete directly with Uber and Careem "
            "in Saudi Arabia, given the current regulatory environment and market saturation?"
        )
    }
    try:
        r = _post(url, payload)
        resp_body = r.json()
        if r.status_code != 202:
            e = _record("E3", "E", "POST", _ws(url), payload, r.status_code, resp_body,
                        flags=[f"Expected 202, got {r.status_code}"])
            _print_entry(e)
            return

        analysis_id = resp_body.get("id")
        classified_as = resp_body.get("classified_as")
        print(f"  classified_as: {classified_as!r}  polling…")
        final = _poll(ws_id, analysis_id)
        if not final:
            e = _record("E3", "E", "POST", _ws(url), payload, 202, resp_body,
                        classified_as=classified_as, final_status="timeout", flags=["Timed out"])
        else:
            results = final.get("results") or {}
            output = results.get("output") or {}
            flags = []
            extra = {"analysis_id": analysis_id,
                     "e3_recommendation": output.get("recommendation")}
            rec = output.get("recommendation")
            risks = output.get("key_risks")
            if rec == "proceed":
                flags.append(
                    f"E3 RC FLAG: recommendation=proceed for saturated/regulated market — "
                    f"check if key_risks contradict this. key_risks: {json.dumps(risks)[:200]}"
                )
            elif rec in ("proceed_with_caution", "do_not_proceed"):
                extra["e3_result"] = f"Expected direction: {rec}"
            e = _record("E3", "E", "POST", _ws(url), payload, 202, resp_body,
                        classified_as=classified_as,
                        final_status=final["status"],
                        output=output,
                        eval_obj=results.get("eval"),
                        citations=results.get("citations"),
                        error_msg=final.get("error"),
                        flags=flags, extra=extra)
        _print_entry(e)
    except Exception as exc:
        e = _record("E3", "E", "POST", _ws(url), payload, -1, {"_error": str(exc)},
                    flags=[f"Exception: {exc}"])
        _print_entry(e)


def run_e4(ws_id: str, completed_analysis_id: str) -> None:
    print(f"\n\n══ E4 — Eval non-determinism (3 re-runs on {completed_analysis_id[:8]}…) ══")
    url = f"/{ws_id}/analyses/{completed_analysis_id}:evaluate"
    eval_runs = []
    for run_i in range(3):
        try:
            r = requests.post(_ws(url), timeout=120)
            if r.status_code == 200:
                ev = (r.json().get("results") or {}).get("eval", {})
                eval_runs.append(ev)
                print(f"  run {run_i+1}: overall_score={ev.get('overall_score')}  passed={ev.get('passed')}")
            else:
                eval_runs.append({"_error": f"HTTP {r.status_code}: {r.text[:100]}"})
                print(f"  run {run_i+1}: ERROR {r.status_code}")
        except Exception as exc:
            eval_runs.append({"_error": str(exc)})
            print(f"  run {run_i+1}: Exception {exc}")

    scores = [e.get("overall_score") for e in eval_runs
              if isinstance(e.get("overall_score"), (int, float))]
    spread = round(max(scores) - min(scores), 4) if len(scores) >= 2 else None
    flags = []
    if spread is not None and spread > 0.10:
        flags.append(
            f"E4 SPREAD: overall_score range {min(scores):.3f}–{max(scores):.3f} "
            f"(spread={spread}) — wide enough to flip 'passed' near 0.75 threshold"
        )
    e = {
        "scenario": "E4", "section": "E",
        "request": {"method": "POST", "url": _ws(url), "body": None},
        "initial_http_status": 200,
        "response_body": None,
        "flags": flags,
        "extra": {
            "analysis_id": completed_analysis_id,
            "eval_runs": eval_runs,
            "score_spread": spread,
            "scores": scores,
        },
    }
    with _log_lock:
        _entries.append(e)
    _print_entry(e)


# ─── section F ─────────────────────────────────────────────────────────────────

def run_f1(ws_id: str) -> None:
    print("\n\n══ F1 — SSE stream for non-existent analysis_id ══")
    fake_id = "00000000-dead-beef-dead-000000000000"
    url = f"/{ws_id}/analyses/{fake_id}/stream"
    flags = []
    try:
        r = requests.get(_ws(url), timeout=10, stream=False)
        if r.status_code == 404:
            pass  # expected
        elif r.status_code == 200:
            flags.append(
                "F1 DOCUMENTED BUG: 200 instead of 404 for non-existent analysis_id "
                "(event_bus.exists() guard missing per §4.4)"
            )
        elif r.status_code == 500:
            flags.append("F1: 500 — event_bus crash on non-existent id")
        else:
            flags.append(f"F1: unexpected status {r.status_code}")
        e = _record("F1", "F", "GET", _ws(url), None, r.status_code,
                    {"status_code": r.status_code, "body": r.text[:300]},
                    flags=flags)
    except requests.exceptions.Timeout:
        e = _record("F1", "F", "GET", _ws(url), None, -1, {"_error": "timed out"},
                    flags=["F1 DOCUMENTED BUG: stream hangs instead of 404 (event_bus guard)"])
    _print_entry(e)


def run_f2(ws_id: str, completed_analysis_id: str) -> None:
    print(f"\n\n══ F2 — SSE stream after completion ({completed_analysis_id[:8]}…) ══")
    url = f"/{ws_id}/analyses/{completed_analysis_id}/stream"
    flags = []
    events = _read_sse(ws_id, completed_analysis_id, timeout=15)
    if not events:
        flags.append("F2: No events received")
    elif events[0].get("type") not in ("done", "error"):
        flags.append(
            f"F2: First event was {events[0].get('type')!r} instead of done/error — "
            "stale replay possible"
        )
    if len(events) > 1:
        flags.append(f"F2: Received {len(events)} events — expected exactly 1 immediate done")
    e = _record("F2", "F", "GET", _ws(url), None, 200,
                {"events": events},
                flags=flags,
                extra={"analysis_id": completed_analysis_id, "event_count": len(events),
                       "first_event_type": events[0].get("type") if events else None})
    _print_entry(e)


# ─── A-D captured data (from terminal run) ─────────────────────────────────────

AD_TERMINAL_DATA = [
    # ── Section A ──────────────────────────────────────────────────────────────
    {
        "scenario": "A1", "section": "A",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": "What are my brand's biggest weaknesses vs competitors?"}},
        "initial_http_status": 202,
        "response_body": {"classified_as": "swot"},
        "classified_as": "swot",
        "final_status": "ready",
        "eval": {
            "passed": False, "overall_score": 0.4,
            "flags": [
                "Only 0% of claims have verified citations (need ≥80%)",
                "Incomplete sections: 'strengths' has fewer than 2 items; 'weaknesses' has fewer than 2 items",
                "Low citation grounding: No items with citations available to ground-check",
            ],
            "criteria": [
                {"name": "citation_support_rate", "score": 0.0, "detail": "No items found in output", "passed": False},
                {"name": "section_completeness", "score": 0.0,
                 "detail": "'strengths' has fewer than 2 items; 'weaknesses' has fewer than 2 items", "passed": False},
                {"name": "evidence_grounding", "score": 0.0,
                 "detail": "No items with citations available to ground-check", "passed": False},
                {"name": "recommendation_consistency", "score": 1.0,
                 "detail": "Not applicable for this analysis type", "passed": True},
                {"name": "internal_consistency", "score": 1.0,
                 "detail": "Not enough claims to check for contradictions", "passed": True},
            ],
        },
        "flags": [],
        "extra": {"analysis_id": "be2ef8e2-f9fb-4223-8d8e-3f67103f7ab8",
                  "disclaimer": "هذا التحليل مُولَّد بالذكاء الاصطناعي استناداً إلى مصادر عامة متاحة على الإنترنت. يُعدّ مسودة أولية تستلزم مراجعة متخصص قبل اتخاذ أي قرار استثماري أو استراتيجي."},
        "citations_count": None, "citations": None, "output": None, "error_msg": None,
    },
    {
        "scenario": "A2", "section": "A",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": "How will new e-invoicing regulations affect our operations?"}},
        "initial_http_status": 202,
        "response_body": {"classified_as": "pestel"},
        "classified_as": "pestel",
        "final_status": "ready",
        "eval": {
            "passed": True, "overall_score": 0.8,
            "flags": ["Incomplete sections: 'political' is empty; 'social' is empty"],
            "criteria": [
                {"name": "citation_support_rate", "score": 1.0,
                 "detail": "7/7 items have verified citations (100%)", "passed": True},
                {"name": "section_completeness", "score": 0.0,
                 "detail": "'political' is empty; 'social' is empty", "passed": False},
                {"name": "evidence_grounding", "score": 1.0,
                 "detail": "5/5 sampled claims are grounded in cited sources", "passed": True},
                {"name": "recommendation_consistency", "score": 1.0,
                 "detail": "Not applicable for this analysis type", "passed": True},
                {"name": "internal_consistency", "score": 1.0,
                 "detail": "No contradictions found", "passed": True},
            ],
        },
        "flags": [],
        "extra": {"analysis_id": "6e08d6f1-1a7b-4fbc-bb55-67e26b36d506",
                  "disclaimer": "هذا التحليل مُولَّد بالذكاء الاصطناعي استناداً إلى مصادر عامة متاحة على الإنترنت. يُعدّ مسودة أولية تستلزم مراجعة متخصص قبل اتخاذ أي قرار استثماري أو استراتيجي."},
        "citations_count": None, "citations": None, "output": None, "error_msg": None,
    },
    {
        "scenario": "A3", "section": "A",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": "Should we launch a premium product line in Riyadh?"}},
        "initial_http_status": 202,
        "response_body": {"classified_as": "feasibility"},
        "classified_as": "feasibility",
        "final_status": "ready",
        "eval": {
            "passed": True, "overall_score": 0.9,
            "flags": [],
            "criteria": [
                {"name": "citation_support_rate", "score": 1.0,
                 "detail": "4/4 items have verified citations (100%)", "passed": True},
                {"name": "section_completeness", "score": 1.0,
                 "detail": "All sections complete", "passed": True},
                {"name": "evidence_grounding", "score": 0.5,
                 "detail": "2/4 sampled claims are grounded in cited sources", "passed": False},
                {"name": "recommendation_consistency", "score": 1.0,
                 "detail": "The recommendation to 'proceed with caution' is strongly supported. "
                 "The rationale accurately identifies a complete lack of market data for zabady "
                 "in the provided sources, which are for unrelated products, making a premium "
                 "launch highly risky without further research.", "passed": True},
                {"name": "internal_consistency", "score": 1.0,
                 "detail": "Not applicable for this analysis type", "passed": True},
            ],
        },
        "flags": [],
        "extra": {"analysis_id": "94bb1ac9-ec93-4907-bf1f-d51e15fd5973",
                  "disclaimer": "هذا التحليل مُولَّد بالذكاء الاصطناعي استناداً إلى مصادر عامة متاحة على الإنترنت. يُعدّ مسودة أولية تستلزم مراجعة متخصص قبل اتخاذ أي قرار استثماري أو استراتيجي."},
        "citations_count": None, "citations": None, "output": None, "error_msg": None,
    },
    {
        "scenario": "A4", "section": "A",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": "Is our messaging consistent with how our target audience sees us?"}},
        "initial_http_status": 202,
        "response_body": {"classified_as": "brand_analysis"},
        "classified_as": "brand_analysis",
        "final_status": "ready",
        "eval": {
            "passed": False, "overall_score": 0.6,
            "flags": [
                "Only 0% of claims have verified citations (need ≥80%)",
                "Low citation grounding: 0/3 sampled claims are grounded in cited sources",
            ],
            "criteria": [
                {"name": "citation_support_rate", "score": 0.0,
                 "detail": "0/3 items have verified citations (0%)", "passed": False},
                {"name": "section_completeness", "score": 1.0,
                 "detail": "All sections complete", "passed": True},
                {"name": "evidence_grounding", "score": 0.0,
                 "detail": "0/3 sampled claims are grounded in cited sources", "passed": False},
                {"name": "recommendation_consistency", "score": 1.0,
                 "detail": "Not applicable for this analysis type", "passed": True},
                {"name": "internal_consistency", "score": 1.0,
                 "detail": "Not applicable for this analysis type", "passed": True},
            ],
        },
        "flags": [],
        "extra": {"analysis_id": "833195a6-88b7-474e-9d1b-a5065a465e7b",
                  "disclaimer": "هذا التحليل مُولَّد بالذكاء الاصطناعي استناداً إلى مصادر عامة متاحة على الإنترنت. يُعدّ مسودة أولية تستلزم مراجعة متخصص قبل اتخاذ أي قرار استثماري أو استراتيجي."},
        "citations_count": None, "citations": None, "output": None, "error_msg": None,
    },
    {
        "scenario": "A5", "section": "A",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": "What does the competitive landscape look like for our industry right now?"}},
        "initial_http_status": 202,
        "response_body": {"classified_as": "market_research"},
        "classified_as": "market_research",
        "final_status": "ready",
        "eval": {
            "passed": True, "overall_score": 0.96,
            "flags": [],
            "criteria": [
                {"name": "citation_support_rate", "score": 1.0,
                 "detail": "8/8 items have verified citations (100%)", "passed": True},
                {"name": "section_completeness", "score": 1.0,
                 "detail": "All sections complete", "passed": True},
                {"name": "evidence_grounding", "score": 0.8,
                 "detail": "4/5 sampled claims are grounded in cited sources", "passed": True},
                {"name": "recommendation_consistency", "score": 1.0,
                 "detail": "Not applicable for this analysis type", "passed": True},
                {"name": "internal_consistency", "score": 1.0,
                 "detail": "Not applicable for this analysis type", "passed": True},
            ],
        },
        "flags": [],
        "extra": {"analysis_id": "bf4f7578-db67-44ff-b6c5-ae226f3c699e",
                  "disclaimer": "هذا التحليل مُولَّد بالذكاء الاصطناعي استناداً إلى مصادر عامة متاحة على الإنترنت. يُعدّ مسودة أولية تستلزم مراجعة متخصص قبل اتخاذ أي قرار استثماري أو استراتيجي."},
        "citations_count": None, "citations": None, "output": None, "error_msg": None,
    },
    # ── Section B ──────────────────────────────────────────────────────────────
    {
        "scenario": "B1-summary", "section": "B",
        "request": {"body": {"question": "Tell me about the market and our competition."}},
        "initial_http_status": 0, "response_body": None,
        "flags": ["Leakage: 7/7 runs returned 202 (classifier chose market_research every time instead of 'general')"],
        "extra": {
            "b1_summary": {
                "total_runs": 7, "http_202_count": 7, "http_422_count": 0,
                "classification_distribution": {"market_research": 7},
                "leakage_rate_pct": 100.0,
            }
        },
    },
    {
        "scenario": "B2", "section": "B",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": "Tell me everything about my business"}},
        "initial_http_status": 422, "classified_as": "general",
        "response_body": None, "final_status": None,
        "eval": None, "output": None, "citations": None, "citations_count": None,
        "error_msg": None, "flags": [], "extra": {},
    },
    {
        "scenario": "B3", "section": "B",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": "Can you write me a LinkedIn post?"}},
        "initial_http_status": 422, "classified_as": "out_of_scope",
        "response_body": None, "final_status": None,
        "eval": None, "output": None, "citations": None, "citations_count": None,
        "error_msg": None,
        "flags": [
            "B3: decline message apologizes excessively: \"I'm sorry, but I can't help with writing social media posts. My expertise is in providing strategic business analyses su\""
        ],
        "extra": {},
    },
    {
        "scenario": "B4", "section": "B",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": "What's a good subject line for our next newsletter?"}},
        "initial_http_status": 422, "classified_as": "out_of_scope",
        "response_body": None, "final_status": None,
        "eval": None, "output": None, "citations": None, "citations_count": None,
        "error_msg": None, "flags": [], "extra": {},
    },
    {
        "scenario": "B5", "section": "B",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": "Should we give our new hires a signing bonus?"}},
        "initial_http_status": 422, "classified_as": "out_of_scope",
        "response_body": None, "final_status": None,
        "eval": None, "output": None, "citations": None, "citations_count": None,
        "error_msg": None, "flags": [], "extra": {},
    },
    {
        "scenario": "B6", "section": "B",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": "Give me a SWOT and also tell me about the macro environment."}},
        "initial_http_status": 422, "classified_as": "general",
        "response_body": None, "final_status": None,
        "eval": None, "output": None, "citations": None, "citations_count": None,
        "error_msg": None,
        "flags": [
            "Expected HTTP None, got 422",
            "B6: classifier chose 'general' for dual-type question — check if response acknowledges partial coverage",
        ],
        "extra": {},
    },
    # ── Section C (C1-C5 only; C6 captured separately) ─────────────────────────
    {
        "scenario": "C1", "section": "C",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": ""}},
        "initial_http_status": 422, "classified_as": "out_of_scope",
        "response_body": None, "final_status": None,
        "eval": None, "output": None, "citations": None, "citations_count": None,
        "error_msg": None,
        "flags": [
            "Expected HTTP 202, got 422 — note: the harness was checking for 202 per §4.6 ("
            "not rejected by Pydantic), but the classifier actually handled it and returned out_of_scope."
        ],
        "extra": {},
    },
    {
        "scenario": "C2", "section": "C",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": "   "}},
        "initial_http_status": 422, "classified_as": "out_of_scope",
        "response_body": None, "final_status": None,
        "eval": None, "output": None, "citations": None, "citations_count": None,
        "error_msg": None,
        "flags": [
            "Expected HTTP 202, got 422 — same note as C1: classifier returned out_of_scope rather than "
            "passing through to fabricate an analysis."
        ],
        "extra": {},
    },
    {
        "scenario": "C3", "section": "C",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": "...648-char question with UAE luxury D2C pivot detail in back half..."}},
        "initial_http_status": 202, "classified_as": "feasibility",
        "final_status": "ready",
        "eval": {
            "passed": True, "overall_score": 0.85,
            "flags": ["Low citation grounding: 1/4 sampled claims are grounded in cited sources"],
            "criteria": [
                {"name": "citation_support_rate", "score": 1.0,
                 "detail": "4/4 items have verified citations (100%)", "passed": True},
                {"name": "section_completeness", "score": 1.0,
                 "detail": "All sections complete", "passed": True},
                {"name": "evidence_grounding", "score": 0.25,
                 "detail": "1/4 sampled claims are grounded in cited sources", "passed": False},
                {"name": "recommendation_consistency", "score": 1.0,
                 "detail": "The recommendation to not proceed is clearly supported by the rationale, "
                 "which highlights a complete lack of specific market data for the direct-to-consumer "
                 "luxury yogurt market in the UAE. The provided sources are irrelevant to the proposed "
                 "pivot, and the only market information is too general to support the venture.",
                 "passed": True},
                {"name": "internal_consistency", "score": 1.0,
                 "detail": "Not applicable for this analysis type", "passed": True},
            ],
        },
        "response_body": None, "output": None, "citations": None, "citations_count": None,
        "error_msg": None, "flags": [],
        "extra": {
            "analysis_id": "2b6feacc-4992-4dca-b45f-d9f2f4b25590",
            "c3_tail_keywords_found": ["uae", "luxury", "direct-to-consumer", "pivot", "enterprise contracts"],
            "c3_note": (
                "Truncation test PASSED — tail-detail keywords were found in output despite ~650 chars "
                "of front-loaded generic framing. The recommendation was 'do_not_proceed' referencing "
                "the UAE D2C pivot specifically, so the specific detail was NOT silently dropped."
            ),
        },
    },
    {
        "scenario": "C4", "section": "C",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": "ما هي التهديدات التنافسية الأساسية التي تواجه شركتنا؟"}},
        "initial_http_status": 202, "classified_as": "swot",
        "response_body": None, "final_status": None,
        "eval": None, "output": None, "citations": None, "citations_count": None,
        "error_msg": None, "flags": [],
        "extra": {"c4_note": "Arabic input classified correctly as swot without 500. Analysis not waited — just routing check."},
    },
    {
        "scenario": "C5", "section": "C",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/consult",
                    "body": {"question": "ما هو تحليل SWOT المناسب لعلامتنا التجارية في السوق السعودي؟"}},
        "initial_http_status": 202, "classified_as": "swot",
        "response_body": None, "final_status": None,
        "eval": None, "output": None, "citations": None, "citations_count": None,
        "error_msg": None, "flags": [],
        "extra": {"c5_note": "Mixed Arabic+English (SWOT keyword) input also classified as swot. "
                  "Embedded English term appears to bias correctly rather than differently."},
    },
    # ── Section D ──────────────────────────────────────────────────────────────
    {
        "scenario": "D1", "section": "D",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/analyses:generate",
                    "body": {"analysis_type": "pestel",
                             "context": "We're deciding whether to give our new hires a signing bonus."}},
        "initial_http_status": 202,
        "response_body": None, "classified_as": None,
        "final_status": "ready",
        "eval": {
            "passed": True, "overall_score": 0.8,
            "flags": ["Incomplete sections: 'social' is empty"],
            "criteria": [
                {"name": "citation_support_rate", "score": 1.0,
                 "detail": "8/8 items have verified citations (100%)", "passed": True},
                {"name": "section_completeness", "score": 0.0,
                 "detail": "'social' is empty", "passed": False},
                {"name": "evidence_grounding", "score": 1.0,
                 "detail": "5/5 sampled claims are grounded in cited sources", "passed": True},
                {"name": "recommendation_consistency", "score": 1.0,
                 "detail": "Not applicable for this analysis type", "passed": True},
                {"name": "internal_consistency", "score": 1.0,
                 "detail": "No contradictions found", "passed": True},
            ],
        },
        "output": None, "citations": None, "citations_count": None, "error_msg": None,
        "flags": [],
        "extra": {
            "analysis_id": "02586459-89ba-43c8-8e03-fe56f94bc29f",
            "manual_review": (
                "D1: PESTEL for HR question. eval.passed=True (0.8) — model generated a structurally "
                "valid PESTEL filling in macro-environment context about labor markets and compensation "
                "rather than refusing. Social section is empty (the section most directly relevant to "
                "hiring). Inspect whether the content is generic filler or fabricates a strained "
                "connection to signing bonuses."
            ),
        },
    },
    {
        "scenario": "D2", "section": "D",
        "request": {"method": "POST",
                    "url": "http://localhost:8001/api/workspaces/31760ca1-efa5-42d1-9403-20e623246ff8/analyses:generate",
                    "body": {"analysis_type": "market_research",
                             "context": "What should I name my cat?"}},
        "initial_http_status": 202,
        "response_body": None, "classified_as": None,
        "final_status": "ready",
        "eval": {
            "passed": False, "overall_score": 0.4,
            "flags": [
                "Only 0% of claims have verified citations (need ≥80%)",
                "Incomplete sections: 'segments' is empty; 'key_trends' is empty",
                "Low citation grounding: No items with citations available to ground-check",
            ],
            "criteria": [
                {"name": "citation_support_rate", "score": 0.0,
                 "detail": "No items found in output", "passed": False},
                {"name": "section_completeness", "score": 0.0,
                 "detail": "'segments' is empty; 'key_trends' is empty", "passed": False},
                {"name": "evidence_grounding", "score": 0.0,
                 "detail": "No items with citations available to ground-check", "passed": False},
                {"name": "recommendation_consistency", "score": 1.0,
                 "detail": "Not applicable for this analysis type", "passed": True},
                {"name": "internal_consistency", "score": 1.0,
                 "detail": "Not applicable for this analysis type", "passed": True},
            ],
        },
        "output": None, "citations": None, "citations_count": None, "error_msg": None,
        "flags": [],
        "extra": {
            "analysis_id": "e4f14a8a-6878-4c55-b722-78fdc40c922d",
            "manual_review": (
                "D2: market_research for 'What should I name my cat?' Eval failed (0.4). "
                "segments and key_trends are empty — the model couldn't fill these sections with "
                "the nonsense context. Inspect the raw output to see if it wrote anything for "
                "market_overview/competitive_dynamics or left them empty/generic."
            ),
        },
    },
]


# ─── main ──────────────────────────────────────────────────────────────────────

def main():
    global BASE_URL, WS_ID, OUT_FILE

    parser = argparse.ArgumentParser()
    parser.add_argument("--ws-id", default="31760ca1-efa5-42d1-9403-20e623246ff8")
    parser.add_argument("--completed-analysis-id",
                        default="bf4f7578-db67-44ff-b6c5-ae226f3c699e",
                        help="A ready analysis ID to use for E4 and F2")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    BASE_URL = args.base_url.rstrip("/")
    WS_ID    = args.ws_id
    script_dir = os.path.dirname(os.path.abspath(__file__))
    OUT_FILE = args.out or os.path.join(
        os.path.dirname(script_dir), "my_claude_utils", "eval-run.json"
    )

    print(f"Missing-sections eval harness (C6, E1-E4, F1-F2)")
    print(f"  ws_id               : {WS_ID}")
    print(f"  completed_analysis  : {args.completed_analysis_id}")
    print(f"  out                 : {OUT_FILE}")

    # Seed with A-D data captured from the previous run
    _entries.extend(AD_TERMINAL_DATA)

    # Run missing sections
    run_c6(WS_ID)
    run_e1()
    run_e2(WS_ID)
    run_e3(WS_ID)
    run_e4(WS_ID, args.completed_analysis_id)
    run_f1(WS_ID)
    run_f2(WS_ID, args.completed_analysis_id)

    # Write combined JSON
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w") as fh:
        json.dump(_entries, fh, indent=2, default=str)

    print(f"\n\n{'═'*70}")
    print(f"  Results written to: {OUT_FILE}")
    total   = len(_entries)
    flagged = sum(1 for e in _entries if e.get("flags"))
    print(f"  Total entries : {total}")
    print(f"  Flagged       : {flagged}")
    print()
    if flagged:
        print("FLAGS:")
        for e in _entries:
            if e.get("flags"):
                sc = e.get("scenario","?")
                for f in e["flags"]:
                    print(f"  [{sc}] {f[:120]}")


if __name__ == "__main__":
    main()
