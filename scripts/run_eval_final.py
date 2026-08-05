#!/usr/bin/env python3
"""
Final targeted run: C6, E1, E2, E3, E4, F1 only.
Reads the existing eval-run.json, updates/replaces the relevant entries, writes back.
"""
import json, os, re, sys, threading, time, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

BASE_URL = "http://localhost:8001"
WS_ID    = "31760ca1-efa5-42d1-9403-20e623246ff8"
COMPLETED_ID = "bf4f7578-db67-44ff-b6c5-ae226f3c699e"   # A5 market_research, ready
OUT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "my_claude_utils", "eval-run.json")

_lock = threading.Lock()
_new_entries: dict[str, dict] = {}   # scenario → entry


# ─── helpers ──────────────────────────────────────────────────────────────────

def _ws(path): return f"{BASE_URL}/api/workspaces{path}"
def _post(path, payload, timeout=120): return requests.post(_ws(path), json=payload, timeout=timeout)
def _get(path, timeout=15): return requests.get(_ws(path), timeout=timeout)

def _poll(ws_id, analysis_id, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = _get(f"/{ws_id}/analyses/{analysis_id}")
            if r.status_code == 200:
                b = r.json()
                if b["status"] != "generating":
                    return b
        except Exception:
            pass
        time.sleep(5)
    return None

def _read_sse(ws_id, analysis_id, max_events=10, timeout=15):
    url = _ws(f"/{ws_id}/analyses/{analysis_id}/stream")
    events = []
    try:
        with requests.get(url, stream=True, timeout=timeout) as resp:
            for raw in resp.iter_lines(decode_unicode=True):
                if raw and raw.startswith("data: "):
                    try:
                        evt = json.loads(raw[6:])
                        events.append(evt)
                        if evt.get("type") in ("done", "error") or len(events) >= max_events:
                            break
                    except Exception:
                        pass
    except Exception as e:
        events.append({"_error": str(e)})
    return events

def _create_ws(name):
    for attempt in range(3):
        try:
            r = requests.post(f"{BASE_URL}/api/workspaces", json={"name": name}, timeout=20)
            if r.status_code in (200, 201):
                return r.json()["id"]
            print(f"  _create_ws attempt {attempt+1}: HTTP {r.status_code} {r.text[:80]}")
        except Exception as e:
            print(f"  _create_ws attempt {attempt+1}: {e}")
        time.sleep(2)
    return None

def _set_bp(ws_id, **fields):
    defaults = {"brand_name": "TestBrand", "company_name": "TestCo"}
    defaults.update(fields)
    for attempt in range(3):
        try:
            r = requests.put(_ws(f"/{ws_id}/brand-profile"), json=defaults, timeout=20)
            if r.status_code in (200, 201):
                return True
            print(f"  _set_bp attempt {attempt+1}: HTTP {r.status_code} {r.text[:80]}")
        except Exception as e:
            print(f"  _set_bp attempt {attempt+1}: {e}")
        time.sleep(2)
    return False

def save(scenario, entry):
    with _lock:
        _new_entries[scenario] = entry
    print(f"\n  [{scenario}] http={entry.get('initial_http_status')}  "
          f"final={entry.get('final_status')}  "
          f"flags={[f[:60] for f in entry.get('flags', [])]}")


# ─── C6 ───────────────────────────────────────────────────────────────────────

def run_c6():
    print("\n══ C6 — Thin brand profile ══")
    thin_ws = _create_ws("eval-c6-final")
    if not thin_ws:
        save("C6", {"scenario":"C6","section":"C","flags":["workspace creation failed"],
                    "request":{},"initial_http_status":0,"response_body":None})
        return
    ok = _set_bp(thin_ws, brand_name="ThinBrand", company_name="ThinCo", industry="")
    print(f"  workspace: {thin_ws}  bp_set: {ok}")

    url = f"/{thin_ws}/consult"
    payload = {"question": "What are our biggest weaknesses compared to competitors?"}
    try:
        r = _post(url, payload)
        rb = r.json()
        if r.status_code == 202:
            aid = rb.get("id")
            classified_as = rb.get("classified_as")
            final = _poll(thin_ws, aid)
            if final:
                res = final.get("results") or {}
                save("C6", {
                    "scenario":"C6","section":"C",
                    "request":{"method":"POST","url":_ws(url),"body":payload},
                    "initial_http_status":202,
                    "response_body":rb,
                    "classified_as":classified_as,
                    "final_status":final["status"],
                    "output":res.get("output"),
                    "eval":res.get("eval"),
                    "citations_count":len(res.get("citations") or []),
                    "citations":res.get("citations"),
                    "error_msg":final.get("error"),
                    "flags":["MANUAL REVIEW: does output read as generic (interchangeable with any brand), "
                             "or make unsupported brand-specific claims? (thin profile: industry='')"],
                    "extra":{"analysis_id":aid,
                             "disclaimer":(res.get("disclaimer","")[:200]),
                             "c6_note":"brand profile has industry='' (empty)"},
                })
            else:
                save("C6", {"scenario":"C6","section":"C",
                            "request":{"method":"POST","url":_ws(url),"body":payload},
                            "initial_http_status":202,"response_body":rb,
                            "classified_as":classified_as,"final_status":"timeout",
                            "flags":["Timed out"]})
        else:
            save("C6", {"scenario":"C6","section":"C",
                        "request":{"method":"POST","url":_ws(url),"body":payload},
                        "initial_http_status":r.status_code,"response_body":rb,
                        "flags":[f"Expected 202, got {r.status_code}: {rb}"]})
    except Exception as e:
        save("C6", {"scenario":"C6","section":"C",
                    "request":{"method":"POST","url":_ws(url),"body":payload},
                    "initial_http_status":-1,"response_body":{"_error":str(e)},
                    "flags":[f"Exception: {e}"]})


# ─── E1 ───────────────────────────────────────────────────────────────────────

def run_e1():
    print("\n══ E1 — Niche industry ══")
    niche_ws = _create_ws("eval-e1-final")
    if not niche_ws:
        save("E1", {"scenario":"E1","section":"E","flags":["workspace creation failed"],
                    "request":{},"initial_http_status":0,"response_body":None})
        return
    ok = _set_bp(niche_ws,
                 industry="bespoke hand-painted bismuth crystal jewelry for antique collectors",
                 brand_name="CrystalBismuth Atelier")
    print(f"  workspace: {niche_ws}  bp_set: {ok}")

    url = f"/{niche_ws}/analyses:generate"
    payload = {"analysis_type": "market_research"}
    try:
        r = _post(url, payload, timeout=30)
        rb = r.json()
        if r.status_code != 202:
            save("E1", {"scenario":"E1","section":"E",
                        "request":{"method":"POST","url":_ws(url),"body":payload},
                        "initial_http_status":r.status_code,"response_body":rb,
                        "flags":[f"Expected 202, got {r.status_code}"]})
            return
        aid = rb["id"]
        print(f"  polling {aid}…")
        final = _poll(niche_ws, aid, timeout=180)
        if not final:
            save("E1", {"scenario":"E1","section":"E",
                        "request":{"method":"POST","url":_ws(url),"body":payload},
                        "initial_http_status":202,"response_body":rb,
                        "final_status":"timeout","flags":["Timed out"]})
            return
        res = final.get("results") or {}
        flags, extra = [], {"analysis_id": aid}
        if final["status"] == "failed":
            err = final.get("error","")
            if "Insufficient sources found" in err:
                m = re.search(r"Insufficient sources found \((\d+)\)", err)
                extra["e1_result"] = f"EXPECTED: status=failed, Insufficient sources (N={m.group(1) if m else '?'})"
            else:
                flags.append(f"failed but wrong error: {err!r}")
        else:
            n = len(res.get("citations") or [])
            extra["e1_result"] = f"DDGS returned {n} citations — test inconclusive"
        save("E1", {"scenario":"E1","section":"E",
                    "request":{"method":"POST","url":_ws(url),"body":payload},
                    "initial_http_status":202,"response_body":rb,
                    "final_status":final["status"],
                    "output":res.get("output"),"eval":res.get("eval"),
                    "citations_count":len(res.get("citations") or []),
                    "citations":res.get("citations"),
                    "error_msg":final.get("error"),
                    "flags":flags,"extra":extra})
    except Exception as e:
        save("E1", {"scenario":"E1","section":"E",
                    "request":{"method":"POST","url":_ws(url),"body":payload},
                    "initial_http_status":-1,"response_body":{"_error":str(e)},
                    "flags":[f"Exception: {e}"]})


# ─── E2 ───────────────────────────────────────────────────────────────────────

def run_e2():
    print("\n══ E2 — 5 concurrent /consult requests ══")
    concurrent_ws = []
    for i in range(5):
        cws = _create_ws(f"eval-e2-final-{i}")
        if cws and _set_bp(cws, industry="saas technology", brand_name=f"ConcurrentBrand{i}"):
            concurrent_ws.append(cws)
    if not concurrent_ws:
        concurrent_ws = [WS_ID] * 5
    print(f"  using {len(concurrent_ws)} workspaces")

    question = "What does the competitive landscape look like for our software industry?"
    results = []

    def _one(i, ws):
        url = f"/{ws}/consult"
        payload = {"question": question}
        try:
            r = _post(url, payload)
            rb = r.json()
            if r.status_code == 422:
                detail = rb.get("detail",{})
                cls = detail.get("classification") if isinstance(detail,dict) else None
                return {"i":i,"http":422,"classified_as":cls,"final":None,"ws":ws,"aid":None}
            if r.status_code != 202:
                return {"i":i,"http":r.status_code,"final":None,"ws":ws,"aid":None,
                        "flag":f"got {r.status_code}: {str(rb)[:60]}"}
            aid = rb.get("id")
            classified_as = rb.get("classified_as")
            final = _poll(ws, aid)
            if not final:
                return {"i":i,"http":202,"classified_as":classified_as,"final":"timeout","ws":ws,"aid":aid}
            res = final.get("results") or {}
            return {"i":i,"http":202,"classified_as":classified_as,
                    "final":final["status"],"ws":ws,"aid":aid,
                    "eval":res.get("eval"),"error":final.get("error")}
        except Exception as e:
            return {"i":i,"http":-1,"final":None,"ws":ws,"aid":None,"flag":str(e)}

    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(_one, i, concurrent_ws[i % len(concurrent_ws)]): i for i in range(5)}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            print(f"  req {r['i']+1}: http={r['http']}  final={r.get('final')}  "
                  f"cls={r.get('classified_as')}  flag={r.get('flag','')[:50]}")

    ready   = sum(1 for r in results if r.get("final") == "ready")
    failed  = sum(1 for r in results if r.get("final") == "failed")
    timeout = sum(1 for r in results if r.get("final") == "timeout")
    e422    = sum(1 for r in results if r.get("http") == 422)
    e503    = sum(1 for r in results if r.get("http") == 503)
    summary = {"total":5,"ready":ready,"failed":failed,"timeout":timeout,
               "http_422":e422,"http_503":e503,
               "note":"DDGS throttling may inflate failed count under concurrency vs sequential."}
    print(f"  summary: {summary}")
    save("E2-summary", {
        "scenario":"E2-summary","section":"E",
        "request":{},"initial_http_status":0,"response_body":None,
        "flags":[] if not e503 else [f"E2: {e503}/5 requests got 503 (LLM unavailable — likely rate limit or DNS)"],
        "extra":{"e2_summary":summary,"individual_results":results},
    })
    for r in results:
        save(f"E2-req{r['i']+1}", {
            "scenario":f"E2-req{r['i']+1}","section":"E",
            "request":{"method":"POST","url":_ws(f"/{r['ws']}/consult"),
                       "body":{"question":question}},
            "initial_http_status":r["http"],
            "classified_as":r.get("classified_as"),
            "final_status":r.get("final"),
            "eval":r.get("eval"),
            "error_msg":r.get("error"),
            "flags":[r["flag"]] if r.get("flag") else [],
            "extra":{"analysis_id":r.get("aid"),"workspace_id":r["ws"]},
            "response_body":None,"output":None,"citations":None,"citations_count":None,
        })


# ─── E3 ───────────────────────────────────────────────────────────────────────

def run_e3():
    print("\n══ E3 — Feasibility recommendation consistency ══")
    url = f"/{WS_ID}/consult"
    payload = {"question":
        "Should we launch a new ride-hailing app to compete directly with Uber and Careem "
        "in Saudi Arabia, given the current regulatory environment and market saturation?"}
    try:
        r = _post(url, payload)
        rb = r.json()
        if r.status_code != 202:
            save("E3", {"scenario":"E3","section":"E",
                        "request":{"method":"POST","url":_ws(url),"body":payload},
                        "initial_http_status":r.status_code,"response_body":rb,
                        "flags":[f"Expected 202, got {r.status_code}: {rb}"]})
            return
        aid = rb.get("id")
        classified_as = rb.get("classified_as")
        print(f"  classified_as: {classified_as!r}  polling {aid}…")
        final = _poll(WS_ID, aid)
        if not final:
            save("E3", {"scenario":"E3","section":"E",
                        "request":{"method":"POST","url":_ws(url),"body":payload},
                        "initial_http_status":202,"response_body":rb,
                        "classified_as":classified_as,"final_status":"timeout",
                        "flags":["Timed out"]})
            return
        res = final.get("results") or {}
        output = res.get("output") or {}
        rec = output.get("recommendation")
        risks = output.get("key_risks")
        flags, extra = [], {"analysis_id":aid,"e3_recommendation":rec}
        if rec == "proceed":
            flags.append(
                f"E3 RC FLAG: recommendation=proceed for saturated/regulated market — "
                f"check if key_risks contradict. key_risks: {json.dumps(risks)[:200]}")
        elif rec in ("proceed_with_caution","do_not_proceed"):
            extra["e3_result"] = f"Expected direction: {rec}"
        save("E3", {"scenario":"E3","section":"E",
                    "request":{"method":"POST","url":_ws(url),"body":payload},
                    "initial_http_status":202,"response_body":rb,
                    "classified_as":classified_as,
                    "final_status":final["status"],
                    "output":output,"eval":res.get("eval"),
                    "citations_count":len(res.get("citations") or []),
                    "citations":res.get("citations"),
                    "error_msg":final.get("error"),
                    "flags":flags,"extra":extra})
    except Exception as e:
        save("E3", {"scenario":"E3","section":"E",
                    "request":{"method":"POST","url":_ws(url),"body":payload},
                    "initial_http_status":-1,"response_body":{"_error":str(e)},
                    "flags":[f"Exception: {e}"]})


# ─── E4 ───────────────────────────────────────────────────────────────────────

def run_e4():
    print(f"\n══ E4 — Eval non-determinism (3 re-runs on {COMPLETED_ID[:8]}…) ══")
    url = f"/{WS_ID}/analyses/{COMPLETED_ID}:evaluate"
    eval_runs = []
    for i in range(3):
        try:
            r = requests.post(_ws(url), timeout=120)
            if r.status_code == 200:
                ev = (r.json().get("results") or {}).get("eval", {})
                eval_runs.append(ev)
                print(f"  run {i+1}: overall_score={ev.get('overall_score')}  passed={ev.get('passed')}")
            else:
                eval_runs.append({"_error": f"HTTP {r.status_code}: {r.text[:100]}"})
                print(f"  run {i+1}: ERROR {r.status_code}: {r.text[:60]}")
        except Exception as e:
            eval_runs.append({"_error": str(e)})
            print(f"  run {i+1}: Exception {e}")
        time.sleep(1)   # small gap between eval calls

    scores = [e.get("overall_score") for e in eval_runs
              if isinstance(e.get("overall_score"), (int,float))]
    spread = round(max(scores)-min(scores), 4) if len(scores) >= 2 else None
    flags = []
    if spread is not None and spread > 0.10:
        flags.append(
            f"E4 SPREAD: score range {min(scores):.3f}–{max(scores):.3f} "
            f"(spread={spread}) — may flip 'passed' near 0.75 threshold")
    save("E4", {
        "scenario":"E4","section":"E",
        "request":{"method":"POST","url":_ws(url),"body":None},
        "initial_http_status":200,"response_body":None,
        "flags":flags,
        "extra":{"analysis_id":COMPLETED_ID,
                 "eval_runs":eval_runs,"score_spread":spread,"scores":scores},
    })


# ─── F1 ───────────────────────────────────────────────────────────────────────

def run_f1():
    print("\n══ F1 — SSE stream for non-existent analysis_id ══")
    fake_id = "00000000-dead-beef-dead-000000000000"
    url = f"/{WS_ID}/analyses/{fake_id}/stream"
    flags = []
    try:
        r = requests.get(_ws(url), timeout=10, stream=False)
        if r.status_code == 404:
            pass   # spec says this is the DOCUMENTED BUG (200), but 404 is actually correct
        elif r.status_code == 200:
            flags.append(
                "F1 DOCUMENTED BUG: returned 200 instead of 404 for non-existent analysis_id")
        elif r.status_code == 500:
            flags.append("F1: 500 — event_bus crash on non-existent id")
        else:
            flags.append(f"F1: unexpected status {r.status_code}")
        save("F1", {"scenario":"F1","section":"F",
                    "request":{"method":"GET","url":_ws(url),"body":None},
                    "initial_http_status":r.status_code,
                    "response_body":{"status_code":r.status_code,"body":r.text[:200]},
                    "flags":flags,
                    "extra":{"note":"spec §4.4 says documented bug = 200 instead of 404; "
                             "actual code does check DB so 404 is correct behavior"}})
    except requests.exceptions.Timeout:
        save("F1", {"scenario":"F1","section":"F",
                    "request":{"method":"GET","url":_ws(url),"body":None},
                    "initial_http_status":-1,"response_body":{"_error":"timed out"},
                    "flags":["F1 BUG: stream hangs on non-existent id (no 404 returned before timeout)"]})


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"Final targeted run: C6, E1, E2, E3, E4, F1")
    print(f"  ws_id       : {WS_ID}")
    print(f"  completed   : {COMPLETED_ID}")
    print(f"  out         : {OUT_FILE}")

    # Verify DNS is working before spending time on long runs
    print("\n  DNS check… ", end="", flush=True)
    try:
        r = requests.post(_ws(f"/{WS_ID}/consult"),
                          json={"question": "SWOT test"},
                          timeout=60)
        print(f"classify returned {r.status_code} ({r.json().get('classified_as','?') if r.status_code==202 else r.json().get('detail',{}).get('classification','?')})")
    except Exception as e:
        print(f"FAILED: {e}")
        print("  Aborting — fix LLM connectivity first.")
        sys.exit(1)

    run_c6()
    run_e1()
    run_e2()
    run_e3()
    run_e4()
    run_f1()

    # Load existing JSON, replace/add entries by scenario key
    existing = []
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE) as fh:
            existing = json.load(fh)

    # Build a map of existing entries to replace
    updated = {}
    for e in existing:
        sc = e.get("scenario")
        if sc and sc not in _new_entries:
            updated[sc] = e

    # Merge new entries
    for sc, entry in _new_entries.items():
        updated[sc] = entry

    # Canonical order
    order = (
        ["A1","A2","A3","A4","A5"]
        + ["B1-summary","B2","B3","B4","B5","B6"]
        + ["C1","C2","C3","C4","C5","C6"]
        + ["D1","D2"]
        + ["E1","E2-summary"] + [f"E2-req{i}" for i in range(1,6)] + ["E3","E4"]
        + ["F1","F2"]
    )
    final_list = []
    for sc in order:
        if sc in updated:
            final_list.append(updated[sc])
    # Append anything not in the order list
    for sc, e in updated.items():
        if sc not in order:
            final_list.append(e)

    with open(OUT_FILE, "w") as fh:
        json.dump(final_list, fh, indent=2, default=str)

    print(f"\n{'═'*60}")
    print(f"  Written {len(final_list)} entries to {OUT_FILE}")
    flagged = sum(1 for e in final_list if e.get("flags"))
    print(f"  Flagged entries: {flagged}")
    for e in final_list:
        if e.get("flags"):
            for f in e["flags"]:
                print(f"  [{e['scenario']}] {f[:100]}")

if __name__ == "__main__":
    main()
