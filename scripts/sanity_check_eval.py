"""
Sanity check: run run_eval() with real LLM calls on a known-good vs deliberately-bad SWOT.
Usage: python scripts/sanity_check_eval.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Case A: known-good SWOT ────────────────────────────────────────────────────
# Realistic food-delivery startup SWOT. All items verified, no contradictions.
# Citations are coherent with the claims.

GOOD_CITATIONS = [
    {"title": "Middle East Food Delivery Market Report 2025", "url": "https://example.com/1",
     "snippet": "The Middle East food delivery market grew 28% YoY in 2024, reaching $8.3B. Saudi Arabia leads with 42% share."},
    {"title": "Noon Food Competitive Analysis", "url": "https://example.com/2",
     "snippet": "Noon Food and HungerStation dominate the Saudi market with combined 70% market share. New entrants face high CAC."},
    {"title": "Saudi Consumer Behavior Survey 2025", "url": "https://example.com/3",
     "snippet": "73% of Saudi millennials order food delivery at least once a week. Convenience and variety are top drivers."},
    {"title": "Vision 2030 Food & Hospitality Report", "url": "https://example.com/4",
     "snippet": "Saudi Vision 2030 targets 150 new restaurant brands and hospitality investments of $40B by 2030."},
    {"title": "Cloud Kitchen Trend MENA", "url": "https://example.com/5",
     "snippet": "Cloud kitchens reduce overhead by 60% vs traditional restaurants. MENA cloud kitchen market expected to grow at 18% CAGR."},
    {"title": "Restaurant Technology Adoption KSA", "url": "https://example.com/6",
     "snippet": "78% of Saudi restaurants adopted digital ordering in 2024. AI-driven personalization lifts average order value 22%."},
]

GOOD_SWOT = {
    "strengths": [
        {"point": "Strong growth in digital ordering adoption among target demographic",
         "evidence": "73% of Saudi millennials order weekly, providing a large addressable base.",
         "citation_indices": [2], "unverified": False},
        {"point": "Cloud kitchen model reduces operational overhead significantly",
         "evidence": "Cloud kitchens cut overhead by 60% vs traditional restaurants, improving margin.",
         "citation_indices": [4], "unverified": False},
    ],
    "weaknesses": [
        {"point": "High customer acquisition cost in a market dominated by incumbents",
         "evidence": "HungerStation and Noon Food hold 70% combined share, making CAC elevated for new entrants.",
         "citation_indices": [1], "unverified": False},
        {"point": "Limited brand recognition outside launch city",
         "evidence": "Brand awareness campaigns are costly in a saturated digital advertising environment.",
         "citation_indices": [1], "unverified": False},
    ],
    "opportunities": [
        {"point": "Vision 2030 hospitality investments create tailwinds for restaurant sector",
         "evidence": "Saudi government targets $40B in hospitality investment, opening new venue and partnership opportunities.",
         "citation_indices": [3], "unverified": False},
        {"point": "AI-driven personalization can lift average order values",
         "evidence": "Restaurants using AI personalization see 22% higher AOV according to 2024 adoption data.",
         "citation_indices": [5], "unverified": False},
    ],
    "threats": [
        {"point": "Dominant incumbents with entrenched supply chains and loyalty programs",
         "evidence": "Market leaders' combined 70% share reflects deep supplier and consumer lock-in.",
         "citation_indices": [1], "unverified": False},
        {"point": "Market saturation risk as international chains accelerate Saudi expansion",
         "evidence": "Vision 2030 targets 150 new restaurant brands, intensifying competition for delivery slots.",
         "citation_indices": [3], "unverified": False},
    ],
}

# ── Case B: deliberately bad SWOT ─────────────────────────────────────────────
# Problems injected:
#   - 4 of 8 items have unverified=True (citation_support_rate → 50%, gate fires)
#   - 2 direct contradictions: S1 "strong brand recognition" vs T1 "brand completely unknown"
#   - 2 citation mismatch items: citation_indices point to snippets about an unrelated topic
#     (e.g. cloud kitchen overhead reduction cited as evidence for "brand is unknown")

BAD_CITATIONS = [
    {"title": "Middle East Food Delivery Market Report 2025", "url": "https://example.com/1",
     "snippet": "The Middle East food delivery market grew 28% YoY in 2024, reaching $8.3B. Saudi Arabia leads with 42% share."},
    {"title": "Cloud Kitchen Trend MENA", "url": "https://example.com/2",
     "snippet": "Cloud kitchens reduce overhead by 60% vs traditional restaurants. MENA cloud kitchen market expected to grow at 18% CAGR."},
    {"title": "Restaurant Technology Adoption KSA", "url": "https://example.com/3",
     "snippet": "78% of Saudi restaurants adopted digital ordering in 2024. AI-driven personalization lifts average order value 22%."},
]

BAD_SWOT = {
    "strengths": [
        # CONTRADICTION with T1: claims strong brand recognition
        {"point": "The brand has exceptionally strong recognition across all Saudi demographics and is a household name nationwide",
         "evidence": "Brand surveys confirm top-of-mind awareness in all key segments.",
         "citation_indices": [2],  # cites cloud kitchen overhead snippet — MISMATCH
         "unverified": False},
        # UNVERIFIED: no citations
        {"point": "Proprietary logistics algorithm provides 30% faster delivery than all competitors",
         "evidence": "Internal benchmarks show superior speed.",
         "citation_indices": [], "unverified": True},
    ],
    "weaknesses": [
        # UNVERIFIED: no citations
        {"point": "Funding runway is only 3 months without new investment",
         "evidence": "Financial projections indicate burn rate.",
         "citation_indices": [], "unverified": True},
        # UNVERIFIED: cites valid source but marked unverified due to out-of-range index
        {"point": "Menu variety is limited compared to incumbents",
         "evidence": "Market data shows HungerStation offers 3x more SKUs.",
         "citation_indices": [], "unverified": True},
    ],
    "opportunities": [
        {"point": "Growing smartphone penetration in secondary Saudi cities",
         "evidence": "Digital adoption is expanding beyond Riyadh and Jeddah.",
         "citation_indices": [0], "unverified": False},
        # UNVERIFIED
        {"point": "Untapped B2B catering market worth $500M annually",
         "evidence": "Industry insiders estimate corporate catering demand.",
         "citation_indices": [], "unverified": True},
    ],
    "threats": [
        # CONTRADICTION with S1: claims brand is completely unknown
        {"point": "The brand is completely unknown — zero consumer awareness in target markets, no one has heard of it",
         "evidence": "Brand awareness study found 0% unaided recall.",
         "citation_indices": [2],  # cites cloud kitchen overhead snippet — MISMATCH
         "unverified": False},
        {"point": "Aggressive pricing by Noon Food squeezes unit economics",
         "evidence": "Market leaders' 70% combined share reflects pricing power.",
         "citation_indices": [0], "unverified": False},
    ],
}


async def main():
    from app.agents.eval_agent import run_eval

    print("=" * 70)
    print("CASE A: KNOWN-GOOD SWOT")
    print("=" * 70)
    try:
        result_a = await run_eval("swot", GOOD_SWOT, GOOD_CITATIONS)
        print(json.dumps(result_a.model_dump(), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback; traceback.print_exc()

    print("\n" + "=" * 70)
    print("CASE B: DELIBERATELY BAD SWOT")
    print("=" * 70)
    try:
        result_b = await run_eval("swot", BAD_SWOT, BAD_CITATIONS)
        print(json.dumps(result_b.model_dump(), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback; traceback.print_exc()

    print("\n" + "=" * 70)
    print("DISCRIMINATION SUMMARY")
    print("=" * 70)
    if 'result_a' in dir() and 'result_b' in dir():
        def get_score(result, name):
            for c in result.criteria:
                if c.name == name:
                    return c.score, c.passed
            return None, None

        for criterion in ["citation_support_rate", "section_completeness", "evidence_grounding", "internal_consistency"]:
            sa, pa = get_score(result_a, criterion)
            sb, pb = get_score(result_b, criterion)
            direction = "✓ A>B" if sa is not None and sb is not None and sa > sb else ("= TIE" if sa == sb else "✗ A≤B")
            print(f"{criterion:30s}  A={sa:.2f}({'pass' if pa else 'FAIL'})  B={sb:.2f}({'pass' if pb else 'FAIL'})  {direction}")

        print(f"\n{'overall passed':30s}  A={result_a.passed}  B={result_b.passed}")
        print(f"\nCase B flags:")
        for f in result_b.flags:
            print(f"  • {f}")


if __name__ == "__main__":
    asyncio.run(main())
