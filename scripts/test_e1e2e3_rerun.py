"""
E1 / E2 / E3 rerun against real-industry workspaces.

E1: niche-but-real industry (CrystalBismuth, bespoke bismuth jewelry) — expect hard gate failure
E2: 5 concurrent SWOT requests, each against a distinct saas-technology workspace — test whether
    the original 4/5 failure rate was industry-name-caused or DDGS throttling
E3: feasibility question against saas-technology workspace
"""
import asyncio
import time
import httpx

BASE = "http://localhost:8001/api"

# E1: niche industry (non-empty, hard gate should still fire)
E1_WS = "00f58f0f-8bd9-4677-83f8-9f1d39e978b1"

# E2: 5 distinct saas-technology workspaces (mirrors original test structure — same ws count,
#     different industry)
E2_WORKSPACES = [
    "28400220-46a6-4700-860d-f8ff561ffa2b",  # ConcurrentBrand4
    "4a0772dd-fcbd-4a62-84cb-4fdbff2826f7",  # ConcurrentBrand3
    "209921b1-d0ab-4707-885a-b66204b98e40",  # ConcurrentBrand2
    "b804962b-db21-45d9-bb46-2f3b3c84271b",  # ConcurrentBrand2
    "b461f3aa-cb12-4601-a6d5-b8952a77649e",  # ConcurrentBrand1
]

# E3: feasibility against real industry (same workspace as E2[0])
E3_WS = "28400220-46a6-4700-860d-f8ff561ffa2b"
E3_QUESTION = (
    "Should we launch a new ride-hailing app to compete directly with Uber and Careem "
    "in Saudi Arabia, given the current regulatory environment and market saturation?"
)


async def submit(client, ws_id, analysis_type, label, via_consult=False, question=None):
    if via_consult:
        r = await client.post(
            f"{BASE}/workspaces/{ws_id}/consult",
            json={"question": question},
            timeout=30,
        )
    else:
        r = await client.post(
            f"{BASE}/workspaces/{ws_id}/analyses:generate",
            json={"analysis_type": analysis_type},
            timeout=30,
        )
    if r.status_code not in (202, 422):
        print(f"[{label}] unexpected http={r.status_code}: {r.text[:120]}")
        return None, r.status_code, None
    body = r.json()
    analysis_id = body.get("id")
    classified_as = body.get("classified_as")
    return analysis_id, r.status_code, classified_as


async def poll(client, ws_id, analysis_id, label, max_polls=50):
    for i in range(max_polls):
        await asyncio.sleep(6)
        r = await client.get(
            f"{BASE}/workspaces/{ws_id}/analyses/{analysis_id}", timeout=15
        )
        if r.status_code != 200:
            continue
        body = r.json()
        status = body.get("status")
        if status in ("ready", "failed"):
            return body
    return None


async def run_e1(client):
    print("\n[E1] Niche industry — expect hard gate failure")
    analysis_id, http, _ = await submit(client, E1_WS, "swot", "E1")
    if not analysis_id:
        print(f"[E1] submit failed: http={http}")
        return
    print(f"[E1] submitted: id={analysis_id}")
    result = await poll(client, E1_WS, analysis_id, "E1")
    if result:
        status = result.get("status")
        error = result.get("error", "")
        print(f"[E1] status={status}")
        print(f"[E1] error={repr(error)}")
        if status == "failed":
            old_msg = "Ensure the brand profile has a valid industry"
            new_msg = "please try again in a moment"
            if new_msg in error:
                print("[E1] PASS — hard gate fired with new error message ✓")
            elif old_msg in error:
                print("[E1] FAIL — hard gate fired but OLD error message still present ✗")
            else:
                print(f"[E1] hard gate fired, unexpected message: {repr(error)}")
        else:
            print(f"[E1] UNEXPECTED — expected failure but got status={status}")


async def run_e2(client):
    print("\n[E2] 5 concurrent SWOT requests (saas technology) — throttling diagnostic")
    t0 = time.time()

    # Submit all 5 simultaneously
    tasks = [
        submit(client, ws, "swot", f"E2-{i+1}")
        for i, ws in enumerate(E2_WORKSPACES)
    ]
    results_submit = await asyncio.gather(*tasks)
    submit_elapsed = time.time() - t0
    print(f"[E2] All 5 submitted in {submit_elapsed:.1f}s")

    ids = []
    for i, (aid, http, _) in enumerate(results_submit):
        print(f"[E2-{i+1}] http={http}  id={aid}")
        ids.append((i+1, E2_WORKSPACES[i], aid))

    # Poll all 5 concurrently
    print("[E2] Polling...")
    poll_tasks = [
        poll(client, ws, aid, f"E2-{i}")
        for i, ws, aid in ids if aid
    ]
    poll_results = await asyncio.gather(*poll_tasks)

    total_elapsed = time.time() - t0
    print(f"\n[E2] All settled in {total_elapsed:.1f}s total")
    print(f"{'─'*60}")

    successes, failures = [], []
    for idx, ((req_i, ws, aid), result) in enumerate(zip(ids, poll_results)):
        if result is None:
            failures.append((req_i, "timed out", None))
            print(f"[E2-{req_i}] TIMED OUT")
            continue
        status = result.get("status")
        error = result.get("error") or ""
        results_dict = result.get("results") or {}
        citations = len(results_dict.get("citations") or []) if results_dict else 0
        low_sources = results_dict.get("low_sources") if results_dict else None

        if status == "ready":
            output = results_dict.get("output") or {}
            s = len(output.get("strengths") or [])
            w = len(output.get("weaknesses") or [])
            o = len(output.get("opportunities") or [])
            t = len(output.get("threats") or [])
            eval_score = (results_dict.get("eval") or {}).get("overall_score", "?")
            print(f"[E2-{req_i}] READY  citations={citations}  low_sources={low_sources}  "
                  f"SWOT=S{s}/W{w}/O{o}/T{t}  eval={eval_score}")
            successes.append(req_i)
        else:
            failure_cause = "hard gate" if "try again" in error else "other"
            print(f"[E2-{req_i}] FAILED  error={repr(error[:80])}  cause={failure_cause}")
            failures.append((req_i, error[:60], failure_cause))

    print(f"{'─'*60}")
    print(f"[E2] RESULT: {len(successes)}/5 succeeded, {len(failures)}/5 failed")
    if successes:
        print(f"       succeeded: {successes}")
    if failures:
        for req_i, err, cause in failures:
            print(f"       E2-{req_i} failed ({cause}): {repr(err)}")

    orig_rate = "4/5 failed"
    new_rate = f"{len(failures)}/5 failed"
    print(f"\n[E2] Original (zabady industry): {orig_rate}")
    print(f"[E2] This run  (saas technology): {new_rate}")
    if len(failures) <= 1:
        print("[E2] CONCLUSION: original failures were industry-caused (zabady unsearchable) ✓")
    elif len(failures) >= 3:
        print("[E2] CONCLUSION: failures are DDGS throttling — industry name was not the cause")
    else:
        print("[E2] CONCLUSION: mixed — partial improvement, both factors may contribute")


async def run_e3(client):
    print(f"\n[E3] Feasibility via /consult — real industry, expect status=ready")
    analysis_id, http, classified_as = await submit(
        client, E3_WS, None, "E3",
        via_consult=True, question=E3_QUESTION
    )
    if http == 422:
        print(f"[E3] 422 — classifier blocked (classified_as={classified_as})")
        return
    if not analysis_id:
        print(f"[E3] submit failed: http={http}")
        return
    print(f"[E3] submitted: id={analysis_id}  classified_as={classified_as}")
    result = await poll(client, E3_WS, analysis_id, "E3")
    if not result:
        print("[E3] timed out")
        return
    status = result.get("status")
    error = result.get("error") or ""
    results_dict = result.get("results") or {}
    citations = len(results_dict.get("citations") or []) if results_dict else 0
    eval_score = (results_dict.get("eval") or {}).get("overall_score", "?") if results_dict else "?"
    output = results_dict.get("output") or {}
    rec = output.get("recommendation")
    print(f"[E3] status={status}  citations={citations}  eval={eval_score}  recommendation={repr(rec)}")
    if error:
        print(f"[E3] error={repr(error)}")
    if status == "ready":
        print("[E3] PASS — feasibility completed with real industry ✓")
    else:
        print("[E3] FAIL — unexpected failure with real industry ✗")


async def main():
    async with httpx.AsyncClient() as client:
        # Run E1 first (sequential — quick gate test)
        await run_e1(client)

        # Run E2 and E3 concurrently (E3 uses different workspace from E2)
        await asyncio.gather(run_e2(client), run_e3(client))


asyncio.run(main())
