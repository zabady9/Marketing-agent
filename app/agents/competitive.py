from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from app.agents.base import AgentName, AgentSoftError, gather_searches_with_sse
from app.config import get_settings
from app.schemas.common import ClaimType
from app.schemas.intake import FeasibilityInput
from app.schemas.market import (
    Citation,
    CompetitiveAnalysisOutput,
    CompetitorProfile,
)
from app.schemas.report import LocalizedText
from app.sse import EventQueue, SSEEvent
from app.tools.language import ENGLISH_ONLY_TERMS_NOTE
from app.tools.web_search import SearchResult

logger = logging.getLogger(__name__)

_AGENT = AgentName.COMPETITIVE


# ── Internal LLM schemas ───────────────────────────────────────────────────────

class _CompetitorLLMOutput(BaseModel):
    name: str
    market_position: Literal["leader", "challenger", "niche", "unknown"] = "unknown"
    strengths: list[str]   # in output_language
    weaknesses: list[str]  # in output_language
    citation_indices: list[int] = []  # 0-based indices into flat results list
    # <=25 words. Must name what the cited result specifically says about this
    # competitor (not just "see source [i]") — or say plainly that this is
    # analyst inference with no direct source.
    methodology: str


class _CompetitiveLLMOutput(BaseModel):
    competitors: list[_CompetitorLLMOutput]
    key_differentiators: list[str]  # in output_language — what sets this business apart
    market_gaps: list[str]          # in output_language — opportunities to exploit
    narrative: str                  # competitive landscape text in output_language


def _resolve_citations(
    indices: list[int], all_results: list[SearchResult]
) -> list[Citation]:
    seen: set[str] = set()
    out: list[Citation] = []
    for i in indices:
        if 0 <= i < len(all_results):
            r = all_results[i]
            if r.url not in seen:
                out.append(Citation(url=r.url, title=r.title, snippet=r.snippet))
                seen.add(r.url)
    return out


def _classify_competitor(source: str, citations: list[Citation]) -> ClaimType:
    if citations:
        return ClaimType.VERIFIED_FACT
    return ClaimType.ASSUMPTION if source == "user_provided" else ClaimType.OPINION


class CompetitiveAnalysisAgent:
    def __init__(self) -> None:
        s = get_settings()
        self._llm = ChatGoogleGenerativeAI(
            model=s.reasoning_model,
            google_api_key=s.google_api_key,
            temperature=0,
        )
        self._settings = s

    async def run(
        self, fi: FeasibilityInput, queue: EventQueue
    ) -> CompetitiveAnalysisOutput:
        await queue.put(SSEEvent.AGENT_STARTED, {"agent": _AGENT, "study_id": fi.study_id})

        biz = fi.business_description.value
        geo = fi.target_market_geography.value or "global"
        model_type = fi.business_model_type.value or "business"
        user_competitors = [c["name"] for c in fi.competitors]

        # ── Build queries ─────────────────────────────────────────────────────
        queries: list[str] = [
            f"top {biz} {model_type} competitors {geo} market leaders 2024",
            # Listicle/review-site content tends to be richer in concrete
            # strengths/weaknesses than a generic "top competitors" query.
            f"best {model_type} companies {geo} 2025 comparison",
        ]
        # Targeted lookups for user-provided competitors (cap at 3 to limit Tavily calls)
        for name in user_competitors[:3]:
            queries.append(f"{name} {model_type} features pricing strengths weaknesses")
        # Market-share framing helps ground market_position (leader/challenger/niche).
        queries.append(f"{biz} {model_type} market share {geo} key players 2024 2025")

        # ── Fire all searches concurrently (semaphore(2) still throttles the
        # actual Tavily request rate) ─────────────────────────────────────────
        all_results: list[SearchResult] = await gather_searches_with_sse(
            queue, fi.study_id, _AGENT, queries, self._settings.tavily_api_key, max_results=5,
        )

        if not all_results:
            raise AgentSoftError(
                "All Tavily searches returned empty — cannot analyze competitive landscape."
            )

        # ── Build numbered context for LLM ────────────────────────────────────
        results_context = "\n\n".join(
            f"[{i}] TITLE: {r.title}\n    URL: {r.url}\n    SNIPPET: {r.snippet}"
            for i, r in enumerate(all_results)
        )

        user_competitors_note = (
            f"User-provided competitors (source=user_provided): {', '.join(user_competitors)}\n"
            if user_competitors
            else "No competitors mentioned by user.\n"
        )

        # ── LLM extraction ────────────────────────────────────────────────────
        structured_llm = self._llm.with_structured_output(_CompetitiveLLMOutput)
        try:
            llm_out: _CompetitiveLLMOutput = await structured_llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "You are a competitive intelligence analyst producing a "
                            "feasibility study section.\n"
                            "Using the numbered search results provided:\n"
                            "1. Identify the main competitors (include all user-provided ones).\n"
                            "2. For each competitor, list concrete strengths and weaknesses.\n"
                            "3. Identify what makes the user's business concept different "
                            "(key_differentiators).\n"
                            "4. Identify market gaps or underserved niches (market_gaps).\n"
                            "5. For each competitor, write a `methodology` sentence (<=25 words) "
                            "naming WHAT the cited result specifically says (e.g. 'Cited result [i] "
                            "describes their pricing and lack of a subscription tier') — a reviewer "
                            "must be able to check the citation actually supports this profile. If no "
                            "citation applies, say so plainly, e.g. 'No cited result covers this "
                            "competitor; profile is inferred from general category knowledge.' Do not "
                            "claim a source you did not select as citation_indices.\n"
                            "Cite sources using citation_indices (0-based indices into results).\n"
                            f"Write ALL text fields in language: {fi.output_language}.\n"
                            f"{ENGLISH_ONLY_TERMS_NOTE}"
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"Business concept: {biz}\n"
                            f"Geography: {geo}\n"
                            f"Business model: {model_type}\n"
                            f"{user_competitors_note}\n"
                            f"Search results ({len(all_results)} total):\n{results_context}"
                        )
                    ),
                ]
            )
        except Exception as exc:
            raise AgentSoftError(f"Competitive analysis LLM call failed: {exc}") from exc

        # ── Map LLM output to output schema ───────────────────────────────────
        competitor_profiles: list[CompetitorProfile] = []
        all_cit_urls: set[str] = set()
        all_cits: list[Citation] = []

        # Track which names came from user vs. LLM discovery
        user_name_lower = {n.lower() for n in user_competitors}

        for comp in llm_out.competitors:
            cits = _resolve_citations(comp.citation_indices, all_results)
            source: Literal["user_provided", "estimated"] = (
                "user_provided" if comp.name.lower() in user_name_lower else "estimated"
            )
            competitor_profiles.append(
                CompetitorProfile(
                    name=comp.name,
                    source=source,
                    market_position=comp.market_position,
                    strengths=comp.strengths,
                    weaknesses=comp.weaknesses,
                    citations=cits,
                    claim_type=_classify_competitor(source, cits),
                    methodology=comp.methodology,
                )
            )
            for c in cits:
                if c.url not in all_cit_urls:
                    all_cits.append(c)
                    all_cit_urls.add(c.url)

        output = CompetitiveAnalysisOutput(
            study_id=fi.study_id,
            output_language=fi.output_language,
            competitors=competitor_profiles,
            key_differentiators=llm_out.key_differentiators,
            market_gaps=llm_out.market_gaps,
            narrative=LocalizedText(text=llm_out.narrative, language=fi.output_language),
            all_citations=all_cits,
            search_queries_used=queries,
        )

        await queue.put(SSEEvent.AGENT_COMPLETED, {"agent": _AGENT, "study_id": fi.study_id})
        return output
