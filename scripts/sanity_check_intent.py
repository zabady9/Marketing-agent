"""
Sanity check: run classify_intent() with real Gemini Flash on 7 test questions.
Usage: python scripts/sanity_check_intent.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BRAND = {"industry": "food delivery", "brand_name": "Mhana"}

CASES = [
    ("What are my brand's biggest weaknesses vs competitors?",         "swot"),
    ("What regulations could affect our expansion into UAE?",          "pestel"),
    ("Should we launch a premium product line in Riyadh?",             "feasibility"),
    ("Is our brand messaging resonating with Gen Z?",                  "brand_analysis"),
    ("What does the cloud kitchen market look like in 2025?",          "market_research"),
    ("Tell me everything about my business",                           "general"),
    ("Can you write me a LinkedIn post?",                              "out_of_scope"),
]

PASS_MARK = {"swot", "pestel", "feasibility", "brand_analysis", "market_research"}


async def main():
    from app.agents.intent_agent import classify_intent

    results = []
    for question, expected in CASES:
        result = await classify_intent(question, BRAND)
        ok = result.analysis_type == expected
        results.append((question, expected, result.analysis_type, result.reasoning, result.suggestion, ok))

    print("\n" + "=" * 80)
    print("INTENT CLASSIFIER SANITY CHECK — 7 questions")
    print("=" * 80)

    all_pass = True
    for question, expected, got, reasoning, suggestion, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"\n[{status}] Q: {question!r}")
        print(f"       Expected: {expected:<18}  Got: {got}")
        print(f"       Reasoning: {reasoning}")
        if suggestion:
            print(f"       Suggestion: {suggestion}")
        if not ok:
            all_pass = False

    print("\n" + "=" * 80)
    passed = sum(1 for *_, ok in results if ok)
    print(f"Result: {passed}/7 correct")

    # Required: first 5 must all be correct (they map to actionable types)
    first_five_pass = all(ok for *_, ok in results[:5])
    if first_five_pass:
        print("First 5 (actionable types): ALL PASS — classifier is ready")
    else:
        failures = [(q, exp, got) for q, exp, got, *_, ok in results[:5] if not ok]
        print("First 5 (actionable types): FAILURES — classifier needs prompt revision:")
        for q, exp, got in failures:
            print(f"  '{q}' → expected {exp}, got {got}")

    return 0 if first_five_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
