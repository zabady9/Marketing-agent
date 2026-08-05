"""
Item 2 verification: two-branch test for the scoped MIN_CITATIONS gate.

Branch A (C6) — empty industry → fallback bypass → status=ready, low_sources=true
Branch B (E1) — non-empty but unsearchable industry → gate fires → status=failed, new error msg
"""
import asyncio
import json
import httpx

BASE = "http://localhost:8001/api"

# C6: empty industry workspace
C6_WS = "b503ec57-2ffe-434b-b135-3255be7f8e7e"
# E1: non-empty but unsearchable industry (niche/weird)
E1_WS = "00f58f0f-8bd9-4677-83f8-9f1d39e978b1"


async def verify_brand_profile(client, ws_id, label):
    r = await client.get(f"{BASE}/workspaces/{ws_id}/brand-profile")
    if r.status_code == 200:
        bp = r.json()
        print(f"[{label}] brand profile — industry={repr(bp.get('industry'))}  brand_name={repr(bp.get('brand_name'))}")
    else:
        print(f"[{label}] brand profile fetch failed: {r.status_code} {r.text[:80]}")


async def run_analysis(client, ws_id, label):
    r = await client.post(
        f"{BASE}/workspaces/{ws_id}/analyses:generate",
        json={"analysis_type": "swot"},
        timeout=30,
    )
    print(f"[{label}] POST → http={r.status_code}")
    if r.status_code != 202:
        print(f"[{label}] ERROR: {r.text[:200]}")
        return None
    body = r.json()
    analysis_id = body.get("id")
    print(f"[{label}] analysis_id={analysis_id}")
    return analysis_id


async def poll(client, ws_id, analysis_id, label, max_polls=40):
    for i in range(max_polls):
        await asyncio.sleep(6)
        r = await client.get(f"{BASE}/workspaces/{ws_id}/analyses/{analysis_id}", timeout=15)
        if r.status_code != 200:
            print(f"[{label}] poll {i+1}: GET failed {r.status_code}")
            continue
        body = r.json()
        status = body.get("status")
        print(f"[{label}] poll {i+1}: status={status}")
        if status in ("ready", "failed"):
            return body
    print(f"[{label}] timed out after {max_polls} polls")
    return None


def summarize(label, body):
    if body is None:
        print(f"\n[{label}] NO RESULT")
        return

    status = body.get("status")
    error = body.get("error")
    results = body.get("results") or {}

    print(f"\n{'='*60}")
    print(f"[{label}] FINAL RESULT")
    print(f"  status:      {status}")
    print(f"  error:       {repr(error)}")
    print(f"  low_sources: {results.get('low_sources', 'KEY MISSING')}")
    citations = results.get("citations") or []
    print(f"  citations:   {len(citations)}")

    output = results.get("output") or {}
    if output:
        strengths = output.get("strengths") or []
        weaknesses = output.get("weaknesses") or []
        opps = output.get("opportunities") or []
        threats = output.get("threats") or []
        print(f"  SWOT sections: S={len(strengths)} W={len(weaknesses)} O={len(opps)} T={len(threats)}")
        if strengths:
            first = strengths[0]
            print(f"  strengths[0]: point={repr(str(first.get('point',''))[:120])}")
            print(f"               evidence={repr(str(first.get('evidence',''))[:120])}")
    else:
        print("  output: (empty)")

    eval_result = results.get("eval") or {}
    if eval_result:
        print(f"  eval.score:  {eval_result.get('overall_score', '?')}")
        print(f"  eval.passed: {eval_result.get('passed', '?')}")
    print(f"{'='*60}")


async def main():
    async with httpx.AsyncClient() as client:
        print("=== Verifying brand profiles ===")
        await verify_brand_profile(client, C6_WS, "C6")
        await verify_brand_profile(client, E1_WS, "E1")

        print("\n=== Submitting analyses ===")
        c6_id, e1_id = await asyncio.gather(
            run_analysis(client, C6_WS, "C6"),
            run_analysis(client, E1_WS, "E1"),
        )

        print("\n=== Polling for results ===")
        c6_result, e1_result = await asyncio.gather(
            poll(client, C6_WS, c6_id, "C6") if c6_id else asyncio.sleep(0),
            poll(client, E1_WS, e1_id, "E1") if e1_id else asyncio.sleep(0),
        )

        summarize("C6 (empty industry — bypass branch)", c6_result)
        summarize("E1 (non-empty unsearchable industry — gate branch)", e1_result)


asyncio.run(main())
