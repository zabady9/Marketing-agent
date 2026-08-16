"""Intent classification for the /chat endpoint (18 unified analyst intent types)."""
from __future__ import annotations

from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agents.llm import get_llm



# ── Analyst intent classifier (18 classes) ───────────────────────────────────

_ANALYST_SYSTEM_PROMPT = """\
You are an intent classifier for a strategic market analysis assistant. Your job is to
classify what type of response the user's message requires so the right analysts can handle it.

The assistant's PRIMARY PURPOSE is delivering data-driven market intelligence and analysis:
market research, competitive analysis, quantitative benchmarking, structured reports (SWOT,
PESTEL, feasibility), gap identification, and strategic recommendations.

Intent categories:

TIER 1 — CONVERSATIONAL (no analysis needed):
- casual: Pure greetings, small talk, expressions of thanks or farewell with no embedded task.
  Examples: "أهلاً", "Hello", "مرحبا", "شكرًا", "كيف حالك؟", "bye", "good morning"
- system_question: Questions about what the assistant is, what it can do, or how to use it.
  Examples: "كيف تساعدني؟", "What can you help me with?", "ما الذي تقدمه؟", "What tools do you have?"
- followup_clarification: Short follow-ups that reference a prior response in the conversation.
  Examples: "وضح أكثر", "Give me an example", "Tell me more about point 3", "Can you elaborate?"
- out_of_scope: Clearly non-analysis requests: personal advice, recipes, coding help,
  medical/legal questions, social media post creation, content writing, etc.
  Examples: "What's the weather?", "How do I cook pasta?", "Write me a post", "Fix my Python bug"

TIER 2 — FOCUSED DATA (single specialist, tool-driven):
- trend_lookup: Explicitly time-sensitive questions about what is happening RIGHT NOW.
  REQUIRES a clear recency signal: "now", "today", "this week", "latest", "trending", "recent".
  Examples: "What's trending this week?", "Latest news in our industry", "ما أحدث التطورات الآن؟"
- data_insights: Requests for specific measurable metrics for named entities.
  Examples: "What's X's revenue?", "How many employees does Competitor Y have?",
  "Compare funding raised by these three companies", "كم حجم مبيعات المنافس X؟"
- quantitative_analysis: Requests to compute, compare, or benchmark specific numbers.
  Examples: "What's the CAGR of this sector?", "How does their growth rate compare to industry average?",
  "Calculate the market share of the top 3 players", "قارن نسب النمو بين الشركتين"

TIER 3 — FULL ANALYSIS (core purpose, primary use cases):
- market_research: Understanding the market landscape, industry overview, key players,
  market sizing, consumer trends, and market segments.
  Examples: "ما حجم هذا السوق؟", "Who are the key players?", "What does the market look like?",
  "Tell me about the competitive landscape in this sector"
- competitive_analysis: How the subject compares to rivals, competitor positioning,
  competitor strengths/weaknesses, market dynamics, who the key competitors are.
  Examples: "How do we compare to our competitors?", "What are our main rivals doing?",
  "ما هي التهديدات التنافسية؟", "Map the competitive landscape"
- gap_analysis: Identifying what the subject is LACKING vs competitors or market expectations.
  Examples: "ما الذي ينقصنا؟", "Where are we weak compared to the market?",
  "What capabilities should we build?", "What are our biggest competitive gaps?"
- strategic_recommendation: Requests for prioritized action plans, what to do next,
  strategic roadmap, or data-backed recommendations.
  Examples: "ماذا يجب أن نفعل؟", "What should our next move be?",
  "Give me strategic recommendations", "What should we prioritize?"
- subject_analysis: Deep-dive on the subject's own position, structure, assumptions, or
  internal situation — not comparative, not a formal framework, but a holistic assessment.
  Examples: "Tell me about this company's strategic position", "Analyze where we stand",
  "What is our current situation?", "حلل وضعنا الحالي"

TIER 4 — FORMAL STRUCTURED REPORTS:
- swot: User explicitly requests a SWOT framework analysis.
  Examples: "Do a SWOT analysis", "What are our strengths and weaknesses?",
  "Run a SWOT on this company", "اعمل تحليل SWOT"
- pestel: User explicitly requests a PESTEL macro-environment analysis.
  Examples: "Run a PESTEL analysis", "What's the macro environment like?",
  "Analyze the political and economic factors", "اعمل تحليل PESTEL"
- feasibility: User explicitly requests a go/no-go feasibility study for a specific decision.
  Requires a decision to evaluate with market data and risk assessment.
  Examples: "Should we expand to this market?", "Is this worth pursuing?",
  "Run a feasibility study on launching X", "دراسة جدوى لإطلاق منتج جديد"
- general_analysis: The request spans 2+ distinct analysis frameworks without a clear dominant one.
  Use when a thoughtful analyst could make an equal case for two different framework types.
  Examples: "Tell me everything about the market and how we compare",
  "Give me a full analysis of our situation and the competitive landscape"

TIER 5 — SETUP / RETRIEVAL:
- setup_subject: User wants to define, update, or configure the subject of analysis.
  Examples: "Update our company profile", "Change the industry we're analyzing",
  "Add a new competitor to track", "عدّل ملف الشركة"
- report_retrieval: User wants to retrieve or view a previously generated formal report.
  Examples: "Show me the SWOT we ran last week", "Get me the latest feasibility report",
  "What did the analysis say?", "أرني التقرير السابق"

Classification rules:
1. A message with BOTH a greeting AND a task → classify as the TASK intent, not casual.
   Example: "أهلاً، ما هي التهديدات التنافسية؟" → competitive_analysis
2. out_of_scope for ANY content creation request (write a post, draft copy, create content).
   This assistant does not create content — it analyzes and researches.
3. swot/pestel/feasibility ONLY when the user explicitly names the framework or clearly
   describes its output. "What are our strengths?" → swot. "Analyze our situation" → subject_analysis.
4. competitive_analysis vs gap_analysis: competitive_analysis = "how do rivals compare / what are
   rivals doing"; gap_analysis = "what do WE lack / what should WE improve"
5. trend_lookup vs market_research: trend_lookup REQUIRES an explicit recency signal ("now", "latest",
   "this week"). Without that signal, classify as market_research.
6. data_insights vs market_research: data_insights = specific metrics for specific named entities;
   market_research = broad landscape understanding.
7. quantitative_analysis vs data_insights: data_insights = retrieve specific metrics;
   quantitative_analysis = compute/compare/benchmark the numbers already retrieved.
8. strategic_recommendation vs competitive_analysis: asking what to DO → strategic_recommendation;
   asking what the competition IS DOING → competitive_analysis.
9. followup_clarification ONLY when the message is clearly a follow-up with no new task.
   A standalone question is never followup_clarification even if it's short.
10. "ارسملي" / "أرسم لي" / "show me" + an analysis topic = the ANALYSIS intent, not out_of_scope.
    Visualization happens automatically after analysis.
"""


class AnalystIntentClassification(BaseModel):
    intent: Literal[
        "casual",
        "system_question",
        "followup_clarification",
        "out_of_scope",
        "trend_lookup",
        "data_insights",
        "quantitative_analysis",
        "market_research",
        "competitive_analysis",
        "gap_analysis",
        "strategic_recommendation",
        "subject_analysis",
        "swot",
        "pestel",
        "feasibility",
        "general_analysis",
        "setup_subject",
        "report_retrieval",
    ]
    reasoning: str


async def classify_analyst_intent(
    user_message: str,
    brand_profile: dict,
) -> AnalystIntentClassification:
    """Classify a chat message into one of 18 analyst intent categories for routing."""
    industry = brand_profile.get("industry") or "unspecified industry"
    subject_name = (
        brand_profile.get("subject_name")
        or brand_profile.get("legal_name")
        or "the subject"
    )

    llm = get_llm("cheap").with_structured_output(AnalystIntentClassification, method="json_schema")
    messages = [
        SystemMessage(content=_ANALYST_SYSTEM_PROMPT),
        # Few-shot: greeting + task → task wins
        HumanMessage(content=(
            "Subject: Acme Corp\nIndustry: food delivery\n\n"
            "Message: أهلاً، ما هي التهديدات التنافسية التي نواجهها؟"
        )),
        AIMessage(content=(
            '{"reasoning": "The message starts with a greeting but immediately embeds a '
            'competitive analysis task. The task intent wins over the greeting.", '
            '"intent": "competitive_analysis"}'
        )),
        # Few-shot: content creation → out_of_scope (this assistant doesn't write content)
        HumanMessage(content=(
            "Subject: Acme Corp\nIndustry: food delivery\n\n"
            "Message: اكتب لي بوست عن إطلاق منتجنا الجديد"
        )),
        AIMessage(content=(
            '{"reasoning": "The user asks to write a post — this is a content creation request. '
            'This assistant focuses on market analysis and research, not content creation. '
            'This is out_of_scope.", '
            '"intent": "out_of_scope"}'
        )),
        # Few-shot: gap analysis vs competitive analysis
        HumanMessage(content=(
            "Subject: Acme Corp\nIndustry: food delivery\n\n"
            "Message: ما الذي ينقصنا مقارنة بالمنافسين؟"
        )),
        AIMessage(content=(
            '{"reasoning": "The user is asking what THEY lack, not how rivals compare. '
            'The focus is on their own gaps and weaknesses. This is gap_analysis.", '
            '"intent": "gap_analysis"}'
        )),
        # Few-shot: explicit SWOT request
        HumanMessage(content=(
            "Subject: Acme Corp\nIndustry: SaaS\n\n"
            "Message: اعمل تحليل SWOT لشركتنا"
        )),
        AIMessage(content=(
            '{"reasoning": "The user explicitly requests a SWOT analysis framework. '
            'This maps directly to swot.", '
            '"intent": "swot"}'
        )),
        # Few-shot: "ارسملي" + market topic = competitive_analysis
        HumanMessage(content=(
            "Subject: قهوة الفجر\nIndustry: specialty coffee\n\n"
            "Message: ارسملي احنا فين من السوق, بالنسبة للمنافسين"
        )),
        AIMessage(content=(
            '{"reasoning": "\'ارسملي\' means \'show me / illustrate\' but the request is for a '
            'competitive market analysis — where we stand vs competitors. This is competitive_analysis.", '
            '"intent": "competitive_analysis"}'
        )),
        # Actual message to classify
        HumanMessage(content=(
            f"Subject: {subject_name}\n"
            f"Industry: {industry}\n\n"
            f"Message: {user_message}"
        )),
    ]
    result: AnalystIntentClassification = await llm.ainvoke(messages)
    return result


