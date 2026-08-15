#!/usr/bin/env python3
"""
Chat intent routing eval harness.

Tests that the 16-class intent classifier routes messages to the correct
response path:
  - Bypass   (Casey only): no bidding_start, no agent_turn_start
  - Focused  (single agent with tools): agent_turn_start present, no bidding_start
  - Full meeting (team discussion): bidding_start + synthesis_start present

Usage:
  python scripts/test_chat_intent.py [--base-url URL] [--ws-id ID] [--timeout N]

Options:
  --base-url   Server base URL (default: http://localhost:8000)
  --ws-id      Workspace ID with an active brand profile (default: auto-detect)
  --timeout    Seconds to wait per SSE stream (default: 120)

Exit code 0 if all tests pass, 1 if any fail.
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

_results: list[tuple[str, str, str]] = []


def _pass(name: str, msg: str = "") -> None:
    _results.append(("PASS", name, msg))
    print(f"  {GREEN}✓ PASS{RESET}  {BOLD}{name}{RESET}" + (f"\n         {DIM}{msg}{RESET}" if msg else ""))


def _fail(name: str, msg: str = "") -> None:
    _results.append(("FAIL", name, msg))
    print(f"  {RED}✗ FAIL{RESET}  {BOLD}{name}{RESET}" + (f"\n         {RED}{msg}{RESET}" if msg else ""))


# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8000"
STREAM_TIMEOUT = 120


def _api(path: str) -> str:
    return f"{BASE_URL}/api{path}"


def _ws(ws_id: str, path: str) -> str:
    return _api(f"/workspaces/{ws_id}{path}")


# ── Workspace helpers ─────────────────────────────────────────────────────────


def _find_workspace_with_brand_profile() -> Optional[str]:
    """Return the first workspace ID that has an active brand profile."""
    try:
        r = requests.get(_api("/workspaces"), timeout=30)
        if r.status_code != 200:
            return None
        for ws in r.json():
            bp = requests.get(_ws(ws["id"], "/brand-profile"), timeout=30)
            if bp.status_code == 200:
                data = bp.json()
                if data.get("brand_name") and data.get("onboarding_status") == "active":
                    return ws["id"]
    except Exception:
        pass
    return None


def _ensure_workspace(ws_id: Optional[str]) -> Optional[str]:
    if ws_id:
        return ws_id
    print(f"\n{CYAN}Auto-detecting workspace with active brand profile…{RESET}")
    found = _find_workspace_with_brand_profile()
    if found:
        print(f"{GREEN}Found workspace: {found}{RESET}")
    else:
        print(f"{RED}No workspace with active brand profile found. "
              f"Pass --ws-id or set one up first.{RESET}")
    return found


# ── Chat session helpers ──────────────────────────────────────────────────────


def _create_session(ws_id: str) -> Optional[str]:
    try:
        r = requests.post(_ws(ws_id, "/chat/sessions"), json={}, timeout=30)
        if r.status_code == 200:
            return r.json()["id"]
    except Exception:
        pass
    return None


def _send_message(ws_id: str, session_id: str, content: str) -> Optional[str]:
    """POST message, return meeting_id (always present now)."""
    try:
        r = requests.post(
            _ws(ws_id, f"/chat/sessions/{session_id}/messages"),
            json={"content": content},
            timeout=30,
        )
        if r.status_code == 202:
            return r.json().get("meeting_id")
    except Exception:
        pass
    return None


def _read_sse_stream(ws_id: str, session_id: str, timeout: int = STREAM_TIMEOUT) -> list[dict]:
    """Consume SSE stream until stream_complete or error, return list of events."""
    url = _ws(ws_id, f"/chat/sessions/{session_id}/stream")
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
                        if evt.get("type") in ("stream_complete", "error"):
                            break
                    except json.JSONDecodeError:
                        pass
    except requests.exceptions.Timeout:
        events.append({"type": "timeout"})
    except Exception as exc:
        events.append({"type": "_read_error", "message": str(exc)})
    return events


def _event_types(events: list[dict]) -> set[str]:
    return {e.get("type", "") for e in events}


# ── Test runner ───────────────────────────────────────────────────────────────

def _run_test(
    ws_id: str,
    test_id: str,
    message: str,
    expected_path: str,  # "bypass", "focused", or "meeting"
    description: str = "",
) -> None:
    """Create a fresh session, send one message, assert event pattern."""
    # Fresh session per test to avoid cross-contamination
    session_id = _create_session(ws_id)
    if not session_id:
        _fail(test_id, f"{description!r} — could not create session")
        return

    meeting_id = _send_message(ws_id, session_id, message)
    if not meeting_id:
        _fail(test_id, f"{description!r} — message POST failed (no meeting_id returned)")
        return

    # Give the background task a moment to pick up before we open the stream
    time.sleep(0.3)

    events = _read_sse_stream(ws_id, session_id)
    types = _event_types(events)

    label = f'[{test_id}] "{message}"'
    has_bidding     = "bidding_start" in types
    has_agent_turn  = "agent_turn_start" in types
    has_synthesis   = "synthesis_start" in types
    has_done        = "done" in types
    has_complete    = "stream_complete" in types
    has_error       = "error" in types
    has_timeout     = "timeout" in types

    if has_error:
        _fail(test_id, f"{label} — got error event: {next(e for e in events if e.get('type')=='error')}")
        return

    if has_timeout:
        _fail(test_id, f"{label} — stream timed out after {STREAM_TIMEOUT}s")
        return

    if not has_complete:
        _fail(test_id, f"{label} — stream_complete never received (events: {types})")
        return

    if not has_done:
        _fail(test_id, f"{label} — done event missing (events: {types})")
        return

    if expected_path == "bypass":
        if has_bidding or has_agent_turn:
            _fail(test_id, f"{label} — bypass expected but got bidding/agent_turn (events: {types})")
        else:
            _pass(test_id, f"{description} → bypass (Casey direct response)")

    elif expected_path == "focused":
        if has_bidding:
            _fail(test_id, f"{label} — focused expected but got bidding_start (events: {types})")
        elif not has_agent_turn:
            _fail(test_id, f"{label} — focused expected but no agent_turn_start (events: {types})")
        else:
            agent = next((e.get("agent") for e in events if e.get("type") == "agent_turn_start"), "?")
            _pass(test_id, f"{description} → focused (agent: {agent})")

    elif expected_path == "meeting":
        if not has_bidding:
            _fail(test_id, f"{label} — full meeting expected but no bidding_start (events: {types})")
        elif not has_synthesis:
            _fail(test_id, f"{label} — full meeting expected but no synthesis_start (events: {types})")
        else:
            _pass(test_id, f"{description} → full team meeting")

    else:
        _fail(test_id, f"Unknown expected_path: {expected_path!r}")


# ── Test cases ────────────────────────────────────────────────────────────────

TEST_CASES = [
    # ── Tier 1: Bypass — casual ──────────────────────────────────────────────
    ("C1",  "أهلاً",                    "bypass",  "Arabic greeting"),
    ("C2",  "مرحبا",                    "bypass",  "Arabic greeting variant"),
    ("C3",  "كيف حالك؟",               "bypass",  "Arabic small talk"),
    ("C4",  "Hello",                    "bypass",  "English greeting"),
    ("C5",  "Hi there",                 "bypass",  "English greeting variant"),
    ("C6",  "شكرًا جزيلاً",             "bypass",  "Arabic thanks"),
    ("C7",  "Good morning!",            "bypass",  "English morning greeting"),

    # ── Tier 1: Bypass — system_question ────────────────────────────────────
    ("SQ1", "كيف يمكنك مساعدتي؟",       "bypass",  "Arabic capabilities question"),
    ("SQ2", "What can you help me with?","bypass",  "English capabilities question"),
    ("SQ3", "ما الأدوات المتاحة لديك؟", "bypass",  "Arabic tools question"),

    # ── Tier 1: Bypass — out_of_scope ───────────────────────────────────────
    ("OS1", "What's the weather today?", "bypass",  "Out of scope: weather"),
    ("OS2", "How do I cook pasta?",      "bypass",  "Out of scope: recipe"),

    # ── Tier 2: Focused — trend_lookup ──────────────────────────────────────
    ("TL1", "ما أحدث الهاشتاقات في مجالنا الآن؟",  "focused", "Arabic trend lookup"),
    ("TL2", "What's trending this week in our industry?", "focused", "English trend lookup"),

    # ── Tier 2: Focused — data_insights ─────────────────────────────────────
    ("DI1", "كم عدد متابعي المنافس الرئيسي لنا؟",   "focused", "Arabic data lookup"),
    ("DI2", "Compare our engagement rate to Competitor X", "focused", "English data insights"),

    # ── Tier 2: Focused — plan_generation ───────────────────────────────────
    ("PG1", "ابدأ تخطيط المحتوى لهذا الأسبوع",     "focused", "Arabic plan generation"),
    ("PG2", "Generate a 7-day content plan",         "focused", "English plan generation"),

    # ── Tier 3: Full meeting — analysis (primary use cases) ──────────────────
    ("MA1", "ما هي التهديدات التنافسية التي نواجهها؟", "meeting", "Arabic competitive analysis"),
    ("MA2", "Do a SWOT analysis for our brand",         "meeting", "English SWOT"),
    ("MA3", "ما حجم سوق خدماتنا في المنطقة؟",          "meeting", "Arabic market research"),
    ("MA4", "هل يجب أن نطلق منتجاً جديداً في هذا السوق؟", "meeting", "Arabic feasibility"),
    ("MA5", "ما الذي ينقصنا مقارنة بالمنافسين؟",       "meeting", "Arabic gap analysis"),

    # ── Tier 4: Full meeting — content (secondary, explicit) ─────────────────
    ("CC1", "اكتب لي بوست عن إطلاق منتجنا الجديد",   "meeting", "Arabic content creation"),
    ("CC2", "Write me a LinkedIn post about our brand", "meeting", "English content creation"),
]


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Chat intent routing eval")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--ws-id", default=None)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    global BASE_URL, STREAM_TIMEOUT
    BASE_URL = args.base_url.rstrip("/")
    STREAM_TIMEOUT = args.timeout

    ws_id = _ensure_workspace(args.ws_id)
    if not ws_id:
        print(f"{RED}Abort: no workspace available.{RESET}")
        return 1

    print(f"\n{BOLD}Chat Intent Routing Eval{RESET}  —  workspace: {ws_id}")
    print(f"Server: {BASE_URL}  |  Stream timeout: {STREAM_TIMEOUT}s")
    print("─" * 70)

    for test_id, message, expected_path, description in TEST_CASES:
        tier = (
            "Bypass" if expected_path == "bypass" else
            "Focused" if expected_path == "focused" else
            "Meeting"
        )
        print(f"\n{CYAN}[{test_id}]{RESET} {DIM}{tier}{RESET}  {message!r}")
        _run_test(ws_id, test_id, message, expected_path, description)

    # Summary
    passed = sum(1 for r in _results if r[0] == "PASS")
    failed = sum(1 for r in _results if r[0] == "FAIL")
    total  = len(_results)

    print("\n" + "─" * 70)
    print(f"{BOLD}Results:{RESET} {GREEN}{passed} passed{RESET}  {RED}{failed} failed{RESET}  / {total} total")

    if failed > 0:
        print(f"\n{RED}Failed tests:{RESET}")
        for status, name, msg in _results:
            if status == "FAIL":
                print(f"  {RED}✗{RESET} {name}: {msg}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
