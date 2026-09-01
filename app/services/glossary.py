"""
Jargon-term glossary — one hand-authored English definition per term (the
canonical source of truth, easy to audit), localized into the study's
output_language via a single cheap-model translation call, cached per
language so it's only ever translated once (see GlossaryCache).

Terms mirror app/tools/language.py::ENGLISH_ONLY_TERMS exactly — these are
the acronyms every agent prompt is told to keep in English regardless of
output language, so they're exactly the terms a non-English reader needs a
definition for.
"""
from __future__ import annotations

import logging
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.glossary_cache import GlossaryCache

logger = logging.getLogger(__name__)

# One clear, plain-language English sentence per term — the canonical
# definition. Keep in sync with app.tools.language.ENGLISH_ONLY_TERMS.
GLOSSARY_TERMS: dict[str, str] = {
    "TAM": "Total Addressable Market — the total demand that exists for a product or service across an entire market, if one company captured all of it.",
    "SAM": "Serviceable Addressable Market — the portion of the TAM a business could realistically reach given its specific geography and business model.",
    "SOM": "Serviceable Obtainable Market — the share of the SAM a business could realistically capture in its first few years, given competition and resources.",
    "ROI": "Return on Investment — the net profit from an investment, shown as a percentage of the amount originally invested.",
    "NPV": "Net Present Value — what a stream of future cash flows is worth in today's money, after discounting for the time value of money.",
    "IRR": "Internal Rate of Return — the discount rate at which an investment's Net Present Value equals exactly zero; used to compare the profitability of different investments.",
    "CAGR": "Compound Annual Growth Rate — the smoothed, year-over-year growth rate of a value over a period of several years.",
    "EBITDA": "Earnings Before Interest, Taxes, Depreciation, and Amortization — a measure of a company's core operating profit, before accounting effects and financing costs.",
    "Capex": "Capital Expenditure — money spent once on long-term assets, such as equipment, property, or initial setup costs.",
    "Opex": "Operating Expenditure — the ongoing, recurring costs of running the business day to day, such as rent, salaries, or utilities.",
    "Break-even": "The point at which total revenue equals total costs, so the business is neither making nor losing money.",
    "KPI": "Key Performance Indicator — a specific, measurable value used to track progress toward a business goal.",
    "MVP": "Minimum Viable Product — the simplest version of a product that can be released to test an idea with real customers.",
    "SaaS": "Software as a Service — software that customers access online on a subscription basis, rather than installing and owning it outright.",
    "B2B": "Business-to-Business — a company that sells its products or services to other businesses, rather than to individual consumers.",
    "B2C": "Business-to-Consumer — a company that sells its products or services directly to individual consumers.",
    "D2C": "Direct-to-Consumer — a company that sells directly to its customers, without going through third-party retailers or distributors.",
}


class _TermDefinition(BaseModel):
    term: str
    definition: str


class _GlossaryTranslation(BaseModel):
    definitions: list[_TermDefinition]


def _base_language(output_language: str) -> str:
    return output_language.split("-")[0].lower()


async def _translate_glossary(target_language: str) -> dict[str, str]:
    """One cheap-model call translating all 17 definitions at once. This is a
    translation task, not "define this acronym from scratch" — we supply the
    canonical English meaning and ask only for a faithful translation of the
    definition text; the term itself (e.g. "TAM") is echoed back unchanged."""
    s = get_settings()
    llm = ChatGoogleGenerativeAI(model=s.cheap_model, google_api_key=s.google_api_key, temperature=0)
    structured_llm = llm.with_structured_output(_GlossaryTranslation)

    terms_text = "\n".join(f"{term}: {definition}" for term, definition in GLOSSARY_TERMS.items())

    try:
        result: _GlossaryTranslation = await structured_llm.ainvoke([
            SystemMessage(
                content=(
                    "You are a professional business/finance translator. You will be given a "
                    "list of English financial/business acronyms with their English definitions. "
                    "Translate ONLY the definition text into the target language — natural, "
                    "plain business language a non-expert reader would understand, one sentence "
                    "each. Do NOT translate or transliterate the acronym/term itself (e.g. 'TAM', "
                    "'ROI') — echo it back exactly as given, unchanged, in the `term` field. "
                    "Return exactly one item per term listed, in the same order."
                )
            ),
            HumanMessage(
                content=f"Target language (BCP-47): {target_language}\n\nTerms:\n{terms_text}"
            ),
        ])
    except Exception as exc:
        logger.warning("Glossary translation failed for language=%s: %s", target_language, exc)
        return dict(GLOSSARY_TERMS)

    translated = {item.term: item.definition for item in result.definitions}
    # Defensive: fall back to English for any term the model dropped, rather
    # than ever surfacing a missing definition.
    for term, english_definition in GLOSSARY_TERMS.items():
        translated.setdefault(term, english_definition)
    return translated


async def get_or_create_glossary(db: Session, output_language: str) -> dict[str, str]:
    """Cached per-language lookup. English needs no translation; every other
    language is translated once and cached in GlossaryCache from then on."""
    base_lang = _base_language(output_language)
    if base_lang == "en":
        return dict(GLOSSARY_TERMS)

    cached = db.get(GlossaryCache, base_lang)
    if cached is not None and cached.deleted_at is None:
        return cached.terms

    translated = await _translate_glossary(base_lang)
    if cached is not None:
        # The row exists but was soft-deleted — the PK is the language itself,
        # so re-insert would collide. Update in place and un-delete instead.
        cached.terms = translated
        cached.deleted_at = None
    else:
        db.add(GlossaryCache(language=base_lang, terms=translated))
    db.commit()
    return translated
