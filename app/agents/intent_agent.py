"""Intent classification — two classifiers:

1. classify_intent()       — for the /consult endpoint (9 consulting analysis types)
2. classify_chat_intent()  — for the /chat endpoint (16 conversational + task types)
"""
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


# ── Chat intent classifier (16 classes) ──────────────────────────────────────

_CHAT_SYSTEM_PROMPT = """\
You are an intent classifier for a marketing intelligence assistant. Your job is to
classify what type of response the user's message requires so the right agents can handle it.

The bot's PRIMARY PURPOSE is market intelligence and advisory: delivering data-driven market
insights, feasibility studies, competitive analysis, gap identification, and actionable
recommendations. Post/content generation is a SECONDARY supporting feature — only triggered
when the user explicitly asks to write or create content.

Intent categories:

TIER 1 — CONVERSATIONAL (no analysis needed):
- casual: Pure greetings, small talk, expressions of thanks or farewell with no embedded task.
  Examples: "أهلاً", "Hello", "مرحبا", "شكرًا", "كيف حالك؟", "bye", "good morning"
- system_question: Questions about what the bot is, what it can do, or how to use it.
  Examples: "كيف تساعدني؟", "What can you help me with?", "ما الذي تقدمه؟", "What tools do you have?"
- followup_clarification: Short follow-ups that reference a prior response in the conversation.
  Examples: "وضح أكثر", "Give me an example", "Tell me more about point 3", "Can you elaborate?",
  "ما معنى هذا؟" (when there's conversation history to reference)
- out_of_scope: Clearly non-marketing requests: personal advice, recipes, general coding help,
  medical/legal questions, poetry for personal use, etc.
  Examples: "What's the weather?", "How do I cook pasta?", "Fix my Python bug", "Write me a love poem"

TIER 2 — FOCUSED DATA (single-agent, tool-driven):
- trend_lookup: Explicitly time-sensitive questions about what is happening RIGHT NOW.
  REQUIRES a clear recency signal: "now", "today", "this week", "latest", "trending", "recent".
  Examples: "ما أحدث الهاشتاقات الآن؟", "What's trending this week?", "Latest news in our industry"
- data_insights: Requests for specific measurable metrics for named entities (competitors, the brand).
  Examples: "كم متابعاً لدى المنافس X؟", "Compare our engagement rate to Y", "What's X's pricing?",
  "How many followers does Competitor Z have?"

TIER 3 — FULL ANALYSIS (core purpose, primary use cases):
- market_research: Understanding the market landscape, industry overview, audience segments,
  key players, market sizing, consumer trends.
  Examples: "ما حجم سوق التوصيل في منطقتنا؟", "Who are the key players in our industry?",
  "What does the market look like for cloud kitchens?", "Tell me about our target audience"
- competitive_analysis: How the brand compares to rivals, competitive positioning, SWOT,
  competitor strengths/weaknesses, market share dynamics.
  Examples: "ما هي التهديدات التنافسية؟", "How do we compare to our competitors?",
  "What are our main rivals doing?", "Do a SWOT analysis"
- feasibility_study: Go/no-go analysis for a specific decision — launch, expansion, new product.
  Requires a decision to evaluate with market data and risk assessment.
  Examples: "هل يجب أن نطلق منتجاً جديداً؟", "Should we expand to Riyadh?",
  "Is this market worth entering?", "Feasibility of launching a premium line"
- brand_analysis: Assessing brand positioning, voice consistency, messaging clarity,
  and audience alignment.
  Examples: "هل رسالتنا التسويقية صحيحة؟", "Is our brand voice consistent?",
  "Does our messaging resonate with Gen Z?", "Assess our brand positioning"
- gap_analysis: Identifying what the brand is LACKING vs competitors or market expectations —
  capability gaps, positioning gaps, what to improve to become more competitive.
  Examples: "ما الذي ينقصنا مقارنة بالمنافسين؟", "Where are we weak?",
  "What should we improve to be more competitive?", "What are our biggest gaps?"
- strategic_recommendation: Requests for prioritized action plans, what to do next,
  strategic roadmap, or data-backed recommendations.
  Examples: "ماذا يجب أن نفعل؟", "What should our next move be?",
  "Give me a strategic plan", "What are your recommendations?",
  "What should we prioritize?"

TIER 4 — CONTENT (secondary, only when explicitly requested):
- content_creation: User explicitly asks to WRITE, DRAFT, or CREATE a specific piece of content.
  REQUIRES explicit creation verbs: "اكتب", "أنشئ", "write", "draft", "create", "compose".
  Examples: "اكتب لي بوست عن منتجنا", "Write a LinkedIn post about our launch",
  "Draft a caption for our Ramadan campaign", "Create ad copy for X"
- content_planning: User explicitly asks to PLAN a content campaign, calendar, or posting strategy.
  Examples: "خطط لحملة رمضانية", "Plan our content for next month",
  "What should we post this week?", "Help me plan a campaign for our product launch"
- content_refinement: User explicitly asks to REVIEW, EDIT, IMPROVE, or CRITIQUE existing content.
  Examples: "راجع هذا البوست", "Improve this caption", "Is this copy on-brand?",
  "Edit my post to sound more professional"

TIER 5 — SYSTEM ACTION:
- plan_generation: User explicitly requests the automated 7-day content plan system.
  REQUIRES explicit plan generation language: "ابدأ تخطيط المحتوى", "generate a content plan",
  "أنشئ خطة نشر أسبوعية", "start the content plan", "create a posting schedule"

Classification rules:
1. A message with BOTH a greeting AND a task → classify as the TASK intent, not casual.
   Example: "أهلاً، ما هي التهديدات التنافسية؟" → competitive_analysis
2. content_creation ONLY when the user uses explicit creation verbs (write, draft, create, اكتب, أنشئ).
   A question about content strategy is NOT content_creation — it is content_planning.
3. competitive_analysis vs gap_analysis: competitive_analysis = "how do rivals compare to us";
   gap_analysis = "what do WE lack / what should WE improve"
4. trend_lookup vs market_research: trend_lookup REQUIRES an explicit recency signal ("now", "latest",
   "this week"). Without that signal, classify as market_research.
5. data_insights vs market_research: data_insights = specific metrics for specific named entities;
   market_research = broad landscape understanding.
6. strategic_recommendation vs competitive_analysis: if the user is asking what to DO (action), it is
   strategic_recommendation; if asking what the competition IS DOING, it is competitive_analysis.
7. followup_clarification ONLY when the message is clearly a follow-up with no new task.
   A standalone question is never followup_clarification even if it's short.
8. When in doubt between two analysis intents, pick the one that better matches what DELIVERABLE
   the user seems to want.
9. "ارسملي" / "أرسم لي" / "show me" + a market/competitive topic = the ANALYSIS intent
   (competitive_analysis, market_research, etc.), NOT a visual request. Visualization happens
   automatically after analysis — there is no separate visual intent.
"""


class ChatIntentClassification(BaseModel):
    intent: Literal[
        "casual",
        "system_question",
        "followup_clarification",
        "out_of_scope",
        "trend_lookup",
        "data_insights",
        "market_research",
        "competitive_analysis",
        "feasibility_study",
        "brand_analysis",
        "gap_analysis",
        "strategic_recommendation",
        "content_creation",
        "content_planning",
        "content_refinement",
        "plan_generation",
    ]
    reasoning: str


async def classify_chat_intent(
    user_message: str,
    brand_profile: dict,
) -> ChatIntentClassification:
    """Classify a chat message into one of 16 intent categories for routing."""
    industry = brand_profile.get("industry") or "unspecified industry"
    brand_name = (
        brand_profile.get("brand_name")
        or brand_profile.get("company_name")
        or "the company"
    )

    llm = get_llm("cheap").with_structured_output(ChatIntentClassification, method="json_schema")
    messages = [
        SystemMessage(content=_CHAT_SYSTEM_PROMPT),
        # Few-shot: greeting + task → task wins
        HumanMessage(content=(
            "Brand: Acme Food Delivery\nIndustry: food delivery\n\n"
            "Message: أهلاً، ما هي التهديدات التنافسية التي نواجهها؟"
        )),
        AIMessage(content=(
            '{"reasoning": "The message starts with a greeting but immediately embeds a '
            'competitive analysis task. The task intent wins over the greeting.", '
            '"intent": "competitive_analysis"}'
        )),
        # Few-shot: explicit content creation
        HumanMessage(content=(
            "Brand: Acme Food Delivery\nIndustry: food delivery\n\n"
            "Message: اكتب لي بوست عن إطلاق منتجنا الجديد"
        )),
        AIMessage(content=(
            '{"reasoning": "The user uses the explicit creation verb \'اكتب\' (write) and asks '
            'for a specific post. This is content_creation.", '
            '"intent": "content_creation"}'
        )),
        # Few-shot: gap analysis vs competitive analysis
        HumanMessage(content=(
            "Brand: Acme Food Delivery\nIndustry: food delivery\n\n"
            "Message: ما الذي ينقصنا مقارنة بالمنافسين؟"
        )),
        AIMessage(content=(
            '{"reasoning": "The user is asking what THEY lack, not how rivals compare. '
            'The focus is on their own gaps and weaknesses. This is gap_analysis.", '
            '"intent": "gap_analysis"}'
        )),
        # Few-shot: "ارسملي" + market topic = competitive_analysis (NOT visual, NOT casual)
        HumanMessage(content=(
            "Brand: قهوة الفجر\nIndustry: specialty coffee\n\n"
            "Message: ارسملي احنا فين من السوق, بالنسبة للمنافسين"
        )),
        AIMessage(content=(
            '{"reasoning": "\'ارسملي\' means \'show me / illustrate\' but the request is for a '
            'NEW competitive market analysis — where we stand vs competitors. This is a research '
            'request that needs the full team, not a chart of prior data. This is competitive_analysis.", '
            '"intent": "competitive_analysis"}'
        )),
        # Actual message to classify
        HumanMessage(content=(
            f"Brand: {brand_name}\n"
            f"Industry: {industry}\n\n"
            f"Message: {user_message}"
        )),
    ]
    result: ChatIntentClassification = await llm.ainvoke(messages)
    return result


# ── Consulting intent classifier (9 classes) — used by /consult endpoint ──────

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
