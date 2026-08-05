#!/usr/bin/env python3
"""
Final clean run for the 4 remaining scenarios: C6, E1, E2, E3.
Pre-conditions:
  - C6 workspace: b503ec57-2ffe-434b-b135-3255be7f8e7e  (thin brand profile)
  - E1 workspace: 00f58f0f-8bd9-4677-83f8-9f1d39e978b1  (niche industry)
  - Main workspace: 31760ca1-efa5-42d1-9403-20e623246ff8
  - Completed analysis (E4/F2 anchor): bf4f7578-db67-44ff-b6c5-ae226f3c699e
"""

import asyncio, httpx, json, time, os, sys

BASE          = "http://localhost:8001/api"
WS_MAIN       = "31760ca1-efa5-42d1-9403-20e623246ff8"
WS_C6         = "b503ec57-2ffe-434b-b135-3255be7f8e7e"
WS_E1         = "00f58f0f-8bd9-4677-83f8-9f1d39e978b1"
OUT           = os.path.join(os.path.dirname(__file__), "../my_claude_utils/eval-run.json")

POLL_INTERVAL = 10   # seconds between polls
POLL_TIMEOUT  = 600  # 10 minutes max per analysis

# ──────────────────────────────────────────────────────────────────────────────

def load_json():
    with open(OUT) as f:
        return json.load(f)

def save_json(data):
    with open(OUT, "w") as f:
        json.dump(data, f, indent=2)

def upsert(data, key, entry):
    for i, e in enumerate(data):
        if e.get("scenario") == key:
            data[i] = entry
            return
    data.append(entry)

# ──────────────────────────────────────────────────────────────────────────────

async def poll_analysis(client, ws_id, analysis_id, label):
    """Poll until ready/failed or timeout. Returns final record."""
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        r = await client.get(f"{BASE}/workspaces/{ws_id}/analyses/{analysis_id}", timeout=30)
        if r.status_code != 200:
            print(f"  [{label}] poll returned {r.status_code}")
            await asyncio.sleep(POLL_INTERVAL)
            continue
        d = r.json()
        st = d.get("status", "?")
        elapsed = int(POLL_TIMEOUT - (deadline - time.time()))
        print(f"  [{label}] status={st} ({elapsed}s elapsed)")
        if st in ("ready", "failed"):
            return d
        await asyncio.sleep(POLL_INTERVAL)
    return None  # timed out

async def ensure_brand_profile_set(client, ws_id, profile):
    """Set brand profile if not already set."""
    r = await client.put(f"{BASE}/workspaces/{ws_id}/brand-profile", json=profile, timeout=30)
    return r.status_code in (200, 201)

# ──────────────────────────────────────────────────────────────────────────────

async def run_c6(client, data):
    print("\n══ C6 — Thin brand profile ══")
    ws_id = WS_C6
    # Set a minimal (thin) brand profile — just brand_name, no products/goals
    profile = {
        "brand_name": "ThinCo",
        "company_name": "ThinCo Inc.",
        "industry": "",
        "products": [],
        "audience_segments": [],
        "goals": [],
        "tone": "",
        "voice_guidelines": "",
        "positioning": "",
        "avoid": []
    }
    ok = await ensure_brand_profile_set(client, ws_id, profile)
    print(f"  thin workspace: {ws_id}  brand-profile set: {ok}")

    question = "What are our biggest weaknesses compared to competitors?"
    r = await client.post(f"{BASE}/workspaces/{ws_id}/consult",
                          json={"question": question}, timeout=30)
    print(f"  /consult → HTTP {r.status_code}")

    entry = {
        "scenario": "C6",
        "section": "C",
        "request": {"method": "POST", "url": f"{BASE}/workspaces/{ws_id}/consult",
                    "body": {"question": question}},
        "http_status": r.status_code,
        "classification": None,
        "final_status": None,
        "output": None,
        "eval": None,
        "flags": []
    }

    if r.status_code == 422:
        body = r.json()
        cls = body.get("detail", {}).get("classification", "?")
        entry["classification"] = cls
        entry["final_status"] = "rejected_422"
        entry["output"] = body
        entry["flags"].append(f"C6: classifier returned {cls} — expected 202 (pass to analysis)")
        print(f"  ⚠ 422: classified as {cls}")
    elif r.status_code == 202:
        body = r.json()
        aid = body.get("analysis_id")
        cls = body.get("classified_as")
        entry["classification"] = cls
        print(f"  classified_as={cls!r}  polling {aid}…")
        rec = await poll_analysis(client, ws_id, aid, "C6")
        if rec is None:
            entry["final_status"] = "timeout"
            entry["flags"].append("Timed out")
        else:
            entry["final_status"] = rec.get("status")
            entry["output"] = rec.get("output")
            entry["eval"] = rec.get("evaluation")
    else:
        entry["flags"].append(f"Unexpected HTTP {r.status_code}: {r.text[:200]}")

    upsert(data, "C6", entry)
    print(f"  [C6] http={entry['http_status']}  final={entry['final_status']}  flags={entry['flags']}")
    return entry

# ──────────────────────────────────────────────────────────────────────────────

async def run_e1(client, data):
    print("\n══ E1 — Niche industry / insufficient citations ══")
    ws_id = WS_E1
    # Ensure brand profile has a very niche industry
    profile = {
        "brand_name": "NicheCo",
        "company_name": "NicheCo Ltd.",
        "industry": "Artisanal small-batch underwater basket weaving",
        "products": ["Hand-woven baskets"],
        "audience_segments": ["collectors"],
        "goals": ["awareness"],
        "tone": "authentic",
        "voice_guidelines": "natural",
        "positioning": "artisan craft",
        "avoid": []
    }
    ok = await ensure_brand_profile_set(client, ws_id, profile)
    print(f"  niche workspace: {ws_id}  brand-profile set: {ok}")

    r = await client.post(f"{BASE}/workspaces/{ws_id}/analyses:generate",
                          json={"analysis_type": "market_research"}, timeout=30)
    print(f"  /analyses:generate → HTTP {r.status_code}")

    entry = {
        "scenario": "E1",
        "section": "E",
        "request": {"method": "POST", "url": f"{BASE}/workspaces/{ws_id}/analyses:generate",
                    "body": {"analysis_type": "market_research"}},
        "http_status": r.status_code,
        "classification": "market_research",
        "final_status": None,
        "output": None,
        "eval": None,
        "flags": []
    }

    if r.status_code == 202:
        body = r.json()
        aid = body.get("analysis_id")
        print(f"  analysis_id={aid}  polling…")
        rec = await poll_analysis(client, ws_id, aid, "E1")
        if rec is None:
            entry["final_status"] = "timeout"
            entry["flags"].append("Timed out")
        else:
            st = rec.get("status")
            entry["final_status"] = st
            entry["output"] = rec.get("output")
            entry["eval"] = rec.get("evaluation")
            err = rec.get("error") or rec.get("output", {}).get("error", "") if isinstance(rec.get("output"), dict) else ""
            entry["extra"] = {"analysis_id": aid, "error": err,
                              "e1_result": "EXPECTED: failed with Insufficient sources (N=0)" if st == "failed" else f"UNEXPECTED: {st}"}
    else:
        entry["flags"].append(f"Unexpected HTTP {r.status_code}: {r.text[:200]}")

    upsert(data, "E1", entry)
    print(f"  [E1] http={entry['http_status']}  final={entry['final_status']}  flags={entry['flags']}")
    return entry

# ──────────────────────────────────────────────────────────────────────────────

async def run_e2(client, data):
    print("\n══ E2 — 5 concurrent /consult requests ══")
    # Use main workspace for all 5 — avoids workspace-creation race conditions
    # The spec just asks for concurrent load test, workspace identity doesn't matter
    ws_id = WS_MAIN
    question = "What are the top market opportunities for our brand in the next 12 months?"

    async def single_req(idx):
        t0 = time.time()
        try:
            r = await client.post(f"{BASE}/workspaces/{ws_id}/consult",
                                  json={"question": question}, timeout=30)
            elapsed = round(time.time() - t0, 2)
            if r.status_code == 202:
                body = r.json()
                cls = body.get("classified_as")
                aid = body.get("analysis_id")
                print(f"  req {idx}: http=202  cls={cls}  aid={aid}  t={elapsed}s")
                return {"idx": idx, "http": 202, "cls": cls, "aid": aid,
                        "ws": ws_id, "elapsed": elapsed, "flags": []}
            else:
                print(f"  req {idx}: http={r.status_code}  t={elapsed}s")
                return {"idx": idx, "http": r.status_code, "cls": None, "aid": None,
                        "ws": ws_id, "elapsed": elapsed,
                        "flags": [f"Expected 202, got {r.status_code}: {r.text[:100]}"]}
        except Exception as ex:
            elapsed = round(time.time() - t0, 2)
            print(f"  req {idx}: EXCEPTION {ex}  t={elapsed}s")
            return {"idx": idx, "http": -1, "cls": None, "aid": None,
                    "ws": ws_id, "elapsed": elapsed, "flags": [str(ex)]}

    # Fire 5 concurrent requests
    tasks = [asyncio.create_task(single_req(i+1)) for i in range(5)]
    results = await asyncio.gather(*tasks)

    successes = [r for r in results if r["http"] == 202]
    print(f"\n  {len(successes)}/5 accepted (202)")

    # Poll all accepted analyses (don't wait too long — 3 min each)
    poll_deadline = time.time() + 240
    pending = [(r["ws"], r["aid"], r["idx"]) for r in successes if r["aid"]]
    final_states = {}
    while pending and time.time() < poll_deadline:
        still_pending = []
        for (ws, aid, idx) in pending:
            rp = await client.get(f"{BASE}/workspaces/{ws}/analyses/{aid}", timeout=20)
            if rp.status_code == 200:
                st = rp.json().get("status", "?")
                if st in ("ready", "failed"):
                    final_states[idx] = rp.json()
                    print(f"  req {idx} → {st}")
                else:
                    still_pending.append((ws, aid, idx))
            else:
                still_pending.append((ws, aid, idx))
        pending = still_pending
        if pending:
            await asyncio.sleep(15)

    # Build summary
    ready_count  = sum(1 for v in final_states.values() if v.get("status") == "ready")
    failed_count = sum(1 for v in final_states.values() if v.get("status") == "failed")
    timeout_count = len(successes) - len(final_states)
    dropped_count = 5 - len(successes)

    summary = {
        "total": 5,
        "accepted_202": len(successes),
        "rejected_422": sum(1 for r in results if r["http"] == 422),
        "rejected_503": sum(1 for r in results if r["http"] == 503),
        "other_error": sum(1 for r in results if r["http"] not in (202, 422, 503)),
        "ready": ready_count,
        "failed": failed_count,
        "timeout": timeout_count,
        "note": "DDGS throttling may inflate failed count under concurrency vs sequential."
    }
    print(f"  summary: {summary}")

    upsert(data, "E2-summary", {
        "scenario": "E2-summary",
        "section": "E",
        "request": {"method": "POST", "url": f"{BASE}/workspaces/{ws_id}/consult",
                    "body": {"question": question, "concurrent": 5}},
        "http_status": 0,
        "classification": None,
        "final_status": None,
        "output": summary,
        "eval": None,
        "flags": []
    })

    for r in results:
        key = f"E2-req{r['idx']}"
        fstates = final_states.get(r["idx"])
        upsert(data, key, {
            "scenario": key,
            "section": "E",
            "request": {"method": "POST", "url": f"{BASE}/workspaces/{ws_id}/consult",
                        "body": {"question": question}},
            "http_status": r["http"],
            "classification": r["cls"],
            "final_status": fstates.get("status") if fstates else ("timeout" if r["http"] == 202 else None),
            "output": fstates.get("output") if fstates else None,
            "eval": fstates.get("evaluation") if fstates else None,
            "flags": r["flags"]
        })
        print(f"  [E2-req{r['idx']}] http={r['http']}  final={fstates.get('status') if fstates else None}  flags={r['flags']}")

# ──────────────────────────────────────────────────────────────────────────────

async def run_e3(client, data):
    print("\n══ E3 — Feasibility recommendation consistency ══")
    ws_id = WS_MAIN
    question = (
        "Should we launch a new ride-hailing app to compete directly with Uber and Careem "
        "in Saudi Arabia, given the current regulatory environment and market saturation?"
    )
    r = await client.post(f"{BASE}/workspaces/{ws_id}/consult",
                          json={"question": question}, timeout=30)
    print(f"  /consult → HTTP {r.status_code}")

    entry = {
        "scenario": "E3",
        "section": "E",
        "request": {"method": "POST", "url": f"{BASE}/workspaces/{ws_id}/consult",
                    "body": {"question": question}},
        "http_status": r.status_code,
        "classification": None,
        "final_status": None,
        "output": None,
        "eval": None,
        "flags": []
    }

    if r.status_code == 202:
        body = r.json()
        cls = body.get("classified_as")
        aid = body.get("analysis_id")
        entry["classification"] = cls
        entry["extra"] = {"analysis_id": aid}
        print(f"  classified_as={cls!r}  polling {aid}…")
        rec = await poll_analysis(client, ws_id, aid, "E3")
        if rec is None:
            entry["final_status"] = "timeout"
            entry["flags"].append("Timed out")
        else:
            entry["final_status"] = rec.get("status")
            entry["output"] = rec.get("output")
            entry["eval"] = rec.get("evaluation")
            # Note recommendation field for the user to review
            rec_val = None
            if isinstance(rec.get("output"), dict):
                rec_val = rec["output"].get("recommendation")
            entry["extra"]["recommendation"] = rec_val
    elif r.status_code == 422:
        body = r.json()
        cls = body.get("detail", {}).get("classification", "?")
        entry["classification"] = cls
        entry["final_status"] = "rejected_422"
        entry["output"] = body
        entry["flags"].append(f"E3: classifier returned {cls} instead of feasibility")
    else:
        entry["flags"].append(f"Unexpected HTTP {r.status_code}: {r.text[:200]}")

    upsert(data, "E3", entry)
    print(f"  [E3] http={entry['http_status']}  final={entry['final_status']}  flags={entry['flags']}")
    return entry

# ──────────────────────────────────────────────────────────────────────────────

async def main():
    print("Final clean run: C6, E1, E2, E3")
    print(f"  WS_C6  : {WS_C6}")
    print(f"  WS_E1  : {WS_E1}")
    print(f"  WS_MAIN: {WS_MAIN}")

    data = load_json()

    async with httpx.AsyncClient() as client:
        # Quick sanity check
        r = await client.get(f"{BASE}/health", timeout=10)
        print(f"\n  health: {r.status_code} {r.json().get('status','?')}")

        # C6 and E1 can run concurrently (different workspaces)
        # E3 uses main workspace — run after E2 to avoid race
        print("\n--- submitting C6 + E1 concurrently ---")
        c6_task = asyncio.create_task(run_c6(client, data))
        e1_task = asyncio.create_task(run_e1(client, data))
        c6_result, e1_result = await asyncio.gather(c6_task, e1_task)
        save_json(data)
        print("\n--- intermediate save (C6+E1 done) ---")

        # E2: 5 concurrent consult requests
        await run_e2(client, data)
        save_json(data)
        print("\n--- intermediate save (E2 done) ---")

        # E3: single feasibility consult
        await run_e3(client, data)
        save_json(data)

    # Final report
    flagged = [e for e in data if e.get("flags")]
    print(f"\n══════════════════════════════════════════════")
    print(f"  Written {len(data)} entries to {OUT}")
    print(f"  Flagged entries: {len(flagged)}")
    for e in flagged:
        for f in e["flags"]:
            print(f"  [{e['scenario']}] {f}")

if __name__ == "__main__":
    asyncio.run(main())
