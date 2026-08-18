from __future__ import annotations

from dataclasses import dataclass, field

# Terms that stay in English regardless of output_language.
# Passed verbatim to every agent system prompt.
ENGLISH_ONLY_TERMS: list[str] = [
    "TAM", "SAM", "SOM",
    "ROI", "NPV", "IRR", "CAGR", "EBITDA",
    "Capex", "Opex",
    "Break-even",
    "KPI", "MVP",
    "SaaS", "B2B", "B2C", "D2C",
]

ENGLISH_ONLY_TERMS_NOTE = (
    "The following terms must remain in English regardless of the output language: "
    + ", ".join(ENGLISH_ONLY_TERMS)
    + "."
)

# BCP-47 codes that require RTL layout on the frontend
RTL_LANGUAGE_CODES: frozenset[str] = frozenset({"ar", "he", "fa", "ur"})


def is_rtl(language_code: str) -> bool:
    base = language_code.split("-")[0].lower()
    return base in RTL_LANGUAGE_CODES


@dataclass
class LanguageDetectionResult:
    language_code: str       # BCP-47, e.g. "ar", "en", "ar-EG"
    confidence: float        # 0.0–1.0
    dialect: str | None = field(default=None)   # e.g. "Egyptian Arabic"
    method: str = field(default="gemini")       # "gemini" | "langdetect" | "fallback"


async def detect_language(
    text: str,
    google_api_key: str,
    cheap_model: str,
) -> LanguageDetectionResult:
    """Gemini flash first (handles short / mixed / Arabizi text), langdetect fallback."""
    try:
        return await _gemini_detect(text, google_api_key, cheap_model)
    except Exception:
        return _langdetect_fallback(text)


async def _gemini_detect(
    text: str,
    google_api_key: str,
    cheap_model: str,
) -> LanguageDetectionResult:
    from pydantic import BaseModel as _BaseModel

    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    class _LangResult(_BaseModel):
        language_code: str
        confidence: float
        dialect: str | None = None

    llm = ChatGoogleGenerativeAI(
        model=cheap_model,
        google_api_key=google_api_key,
        temperature=0,
    )
    structured = llm.with_structured_output(_LangResult)

    result: _LangResult = await structured.ainvoke(
        [
            SystemMessage(
                content=(
                    "You are a language detection expert. "
                    "Identify the language of the provided text. "
                    "Use BCP-47 codes: 'ar' for Arabic MSA, 'ar-EG' for Egyptian Arabic, "
                    "'ar-LB' for Levantine, 'en' for English, etc. "
                    "Handle code-mixed text and Arabizi (Arabic written in Latin script). "
                    "Return the dominant language. Confidence is 0.0–1.0."
                )
            ),
            HumanMessage(content=f"Detect the language of this text:\n\n{text[:1000]}"),
        ]
    )

    return LanguageDetectionResult(
        language_code=result.language_code,
        confidence=result.confidence,
        dialect=result.dialect,
        method="gemini",
    )


def _langdetect_fallback(text: str) -> LanguageDetectionResult:
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0  # deterministic results
        code = detect(text)
        return LanguageDetectionResult(
            language_code=code,
            confidence=0.7,
            method="langdetect",
        )
    except Exception:
        return LanguageDetectionResult(
            language_code="en",
            confidence=0.0,
            method="fallback",
        )
