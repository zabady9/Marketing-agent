"""Intent classification for the /consult endpoint."""
from __future__ import annotations

from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agents.llm import get_llm

_SYSTEM_PROMPT = """\
You are an intent classifier for a strategic business consulting platform.

Given a free-text question and a brand profile, determine which type of structured analysis the question is asking for.

Analysis types:
- swot: Internal business assessment — Strengths, Weaknesses, Opportunities, Threats — including how the business compares to and positions against competitors
- pestel: Macro-environment analysis (Political, Economic, Social, Technological, Environmental, Legal)
- feasibility: Go/no-go feasibility study (market size, risks, viability recommendation)
- brand_analysis: Brand positioning, messaging clarity, and audience alignment assessment
- market_research: External market landscape — segments, consumer trends, and who the key industry players are
- market_comparison: Direct side-by-side metric comparison between the brand and specific named competitors (e.g. follower counts, engagement rates, pricing, campaign activity). Use this when the user wants specific numbers or KPIs compared across 2+ brands — NOT just a general competitive landscape.
- competitive_analysis: Broader competitive landscape analysis — who the players are, their positioning, relative strengths/weaknesses, market share dynamics. More qualitative than market_comparison; no specific metric lookup implied.
- trend_check: Explicitly time-sensitive questions about what is happening NOW or recently — trending topics, current campaign activity, recent algorithm changes, news. The answer requires live up-to-date data; cached or historical data is insufficient.
- general: The question spans 2+ distinct analysis frameworks — e.g., asks about both the external market AND internal competitive positioning, or both macro environment AND brand-level strategy
- out_of_scope: The question is not about strategic business consulting

Rules:
- Classify as "general" when the question makes a substantial claim on 2 or more distinct analysis types — meaning either type could plausibly be the primary deliverable the user wants. A useful test: could a thoughtful analyst make an equally defensible case for two different analysis types? If yes, it is "general".
- Classify as a specific type only when the question clearly has one dominant framing and the other types would only be incidental context inside that analysis.
- market_comparison vs competitive_analysis: Use market_comparison when the user asks for specific numbers/metrics for named competitors ("how many followers does X have", "compare our pricing to Y"). Use competitive_analysis when the question is about the broader competitive picture without specific metric lookups.
- trend_check boundary: only use this when the question explicitly references recency ("this week", "recently", "now", "latest", "what's trending") or asks about data that is inherently time-bound (trending hashtags, current algorithm behaviour, recent news). Do not use it just because the topic involves competitors.
- Do NOT treat topic coverage as ownership. "Competition" appears inside market_research, feasibility, SWOT, and market_comparison outputs — a question mentioning competition is NOT automatically market_comparison or market_research. Ask what deliverable the user wants.
- Concrete boundary examples:
    * "Tell me about the market and our competition" → GENERAL. "Market" activates market_research; "competition" activates both market_research and SWOT threats. Neither framing dominates.
    * "What are our strengths and what does the market look like for us?" → GENERAL. SWOT and market_research are each half the request.
    * "Who are our main competitors and what market segments should we target?" → market_research. Both sub-questions are fully answered by a market research deliverable.
    * "What's our brand positioning vs. competitors?" → brand_analysis. Competitors are context; the primary deliverable is a brand positioning assessment.
    * "How many followers does Competitor X have compared to us?" → market_comparison. Specific metric, named competitor.
    * "Who are our main competitors and how do they position themselves?" → competitive_analysis. Broad qualitative competitive picture.
    * "What hashtags are trending this week for our industry?" → trend_check. Explicitly time-sensitive.
- "general" is NOT a fallback for vague questions. If a question is broad but maps to one type (e.g., "help me understand my situation" → swot or feasibility), pick the most probable specific type.
- "out_of_scope" is for clearly non-business questions: social media content creation, personal advice, writing tasks.
- If "general": set suggestion to a short clarifying question naming the two most plausible analysis types (e.g., "Are you looking for a full competitive SWOT breakdown, or a broader market landscape and segments overview?"). Do NOT begin with "I'm sorry" or any apology phrase.
- If "out_of_scope": set suggestion to a direct one-sentence decline plus a brief note on what the platform can help with instead. Do NOT begin with "I'm sorry" or any apology phrase.
- For all other valid types: set suggestion to null.
"""


class IntentClassification(BaseModel):
    reasoning: str
    analysis_type: Literal[
        "swot", "pestel", "feasibility", "brand_analysis", "market_research",
        "market_comparison", "competitive_analysis", "trend_check",
        "general", "out_of_scope",
    ]
    suggestion: str | None


async def classify_intent(question: str, brand_profile: dict) -> IntentClassification:
    industry = brand_profile.get("industry") or "unspecified industry"
    brand_name = (
        brand_profile.get("brand_name")
        or brand_profile.get("company_name")
        or "the company"
    )

    llm = get_llm("cheap").with_structured_output(IntentClassification, method="json_schema")
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        # Few-shot: the canonical "market + competition" general case
        HumanMessage(content=(
            "Brand: Acme Corp\nIndustry: retail\n\n"
            "Question: Tell me about the market and our competition"
        )),
        AIMessage(content=(
            '{"reasoning": "The question asks about two distinct things: the external '
            'market landscape (market_research) and how the business competes against '
            'rivals (swot threats/weaknesses). Neither framing dominates — a thoughtful '
            'analyst could make an equal case for either a market landscape report or a '
            'competitive SWOT. Classify as general and ask which the user wants.", '
            '"analysis_type": "general", '
            '"suggestion": "Are you looking for an external market overview and competitor '
            'landscape, or an internal SWOT assessment of how you compete against rivals?"}'
        )),
        HumanMessage(content=(
            f"Brand: {brand_name}\n"
            f"Industry: {industry}\n\n"
            f"Question: {question}"
        )),
    ]
    result: IntentClassification = await llm.ainvoke(messages)
    return result
