from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import get_settings
from app.schemas.intake import (
    FieldWithSource,
    FeasibilityInput,
    FeasibilityStartRequest,
    IntakeExtraction,
    Source,
)
from app.sse import EventQueue, SSEEvent
from app.tools.language import (
    ENGLISH_ONLY_TERMS_NOTE,
    detect_language,
)


class IntakeHardBlockError(Exception):
    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        super().__init__(reason)


# Every wizard-structured field the request can supply, mapped to the matching
# IntakeExtraction field it overrides. Applied unconditionally whenever the
# request value is not None (an explicitly-empty "" or [] from a wizard step
# still counts as a user-made choice, not "unset") — this is the generalized
# form of the override pattern that pricing_unit_price/capex_amount/
# opex_monthly_amount used exclusively before the wizard existed; those three
# keep their own handling below since they also clear missing/soft-missing flags.
_OVERRIDE_FIELDS: list[str] = [
    "business_description",
    "problem_statement",
    "unique_value_proposition",
    "target_market_description",
    "target_market_geography",
    "target_market_type",
    "business_model_type",
    "pricing_model",
    "expected_monthly_sales",
    "funding_source",
    "team_size",
    "key_roles_needed",
    "marketing_channels",
    "competitors",
    "founder_risks",
    "study_goal",
]

_NOTE_LABELS: list[tuple[str, str]] = [
    ("business_description", "Business"),
    ("problem_statement", "Problem"),
    ("unique_value_proposition", "Unique value proposition"),
    ("target_market_description", "Target market"),
    ("target_market_geography", "Geography"),
    ("target_market_type", "Target market type"),
    ("business_model_type", "Business model"),
    ("funding_source", "Funding source"),
    ("study_goal", "Study goal"),
    ("founder_risks", "Founder-stated risks"),
]


def _synthesize_raw_user_input(request: FeasibilityStartRequest) -> str:
    """Built from the wizard's structured fields when the caller doesn't supply
    (or under-supplies) raw_user_input directly, so language detection and LLM
    extraction always have real prose to work with — guaranteed non-trivial
    since business_description alone is required with min_length=20."""
    lines = []
    for field, label in _NOTE_LABELS:
        value = getattr(request, field)
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


class IntakeFeasibilityAgent:
    def __init__(self) -> None:
        s = get_settings()
        self._llm = ChatGoogleGenerativeAI(
            model=s.cheap_model,
            google_api_key=s.google_api_key,
            temperature=0,
        )
        self._settings = s

    async def run(
        self,
        study_id: str,
        request: FeasibilityStartRequest,
        queue: EventQueue,
    ) -> FeasibilityInput:
        # ── 0. Synthesize raw_user_input if the caller didn't supply enough ────
        raw_user_input = request.raw_user_input
        if not raw_user_input or len(raw_user_input.strip()) < 20:
            raw_user_input = _synthesize_raw_user_input(request)

        # ── 1. Language detection ──────────────────────────────────────────────
        lang = await detect_language(
            raw_user_input,
            self._settings.google_api_key,
            self._settings.cheap_model,
        )

        output_language = request.output_language or lang.language_code

        await queue.put(
            SSEEvent.LANGUAGE_DETECTED,
            {
                "study_id": study_id,
                "detected": lang.language_code,
                "dialect": lang.dialect,
                "confidence": lang.confidence,
                "method": lang.method,
                "output_language": output_language,
            },
        )

        # ── 2. Structured field extraction ─────────────────────────────────────
        structured_llm = self._llm.with_structured_output(IntakeExtraction)

        extraction: IntakeExtraction = await structured_llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        "You are an expert business analyst extracting structured data "
                        "from a user's business idea description. "
                        "Extract every field you can from the text. "
                        "If a numeric field (price, budget) is mentioned in any currency, "
                        "convert to that currency and record the ISO-4217 code. "
                        "Set missing_critical_fields to ['pricing_unit_price'] if the user "
                        "gave NO indication of price whatsoever. "
                        "Set soft_missing_fields for fields that are absent but estimable "
                        "(capex, opex_monthly, competitors, team_size). "
                        f"\n{ENGLISH_ONLY_TERMS_NOTE}"
                    )
                ),
                HumanMessage(
                    content=(
                        f"Business idea (language: {lang.language_code}):\n\n"
                        f"{raw_user_input}\n\n"
                        f"Analysis horizon: {request.analysis_horizon_years} years."
                    )
                ),
            ]
        )

        # ── 3. Apply explicit overrides from request ───────────────────────────
        # Wizard-structured fields always win over whatever the LLM extracted.
        # Track which fields were overridden so step 6 can mark them
        # user_provided even when the overridden value is "" or [] (a
        # deliberate empty wizard answer, not "nothing was extracted").
        overridden: set[str] = set()
        for field in _OVERRIDE_FIELDS:
            value = getattr(request, field)
            if value is not None:
                setattr(extraction, field, value)
                overridden.add(field)

        if request.pricing_unit_price is not None:
            extraction.pricing_unit_price = request.pricing_unit_price
            extraction.pricing_currency = request.pricing_currency
            overridden.add("pricing_unit_price")
            extraction.missing_critical_fields = [
                f for f in extraction.missing_critical_fields
                if f != "pricing_unit_price"
            ]
        if request.capex_amount is not None:
            extraction.capex_amount = request.capex_amount
            overridden.add("capex_amount")
            extraction.soft_missing_fields = [
                f for f in extraction.soft_missing_fields if f != "capex"
            ]
        if request.opex_monthly_amount is not None:
            extraction.opex_monthly_amount = request.opex_monthly_amount
            overridden.add("opex_monthly_amount")
            extraction.soft_missing_fields = [
                f for f in extraction.soft_missing_fields if f != "opex_monthly"
            ]

        def _source(field: str, value) -> Source:
            """user_provided if the wizard explicitly set this field (even to
            "" / []), or if the LLM extracted a truthy value; estimated
            (i.e. unknown/left blank) otherwise. Only meaningful for the
            qualitative fields below — numeric fields use their own is-None
            checks since 0 is a legitimate value, not an "unset" sentinel."""
            return Source.USER_PROVIDED if field in overridden or value else Source.ESTIMATED

        # ── 4. Hard block: missing pricing ────────────────────────────────────
        if extraction.pricing_unit_price is None:
            raise IntakeHardBlockError(
                field="pricing_unit_price",
                reason=(
                    "Cannot build a financial model without a unit price. "
                    "Please provide your expected price per unit, subscription fee, "
                    "or transaction value."
                ),
            )

        # ── 5. Soft flags + estimation via web search ─────────────────────────
        capex_missing = extraction.capex_amount is None
        opex_missing = extraction.opex_monthly_amount is None
        sales_missing = extraction.expected_monthly_sales is None

        for field_name in extraction.soft_missing_fields:
            await queue.put(
                SSEEvent.INTAKE_WARNING,
                {
                    "study_id": study_id,
                    "field": field_name,
                    "reason": f"{field_name} not provided — estimating via web research",
                    "fallback": "web_search",
                },
            )

        # Estimate all missing financial inputs in one batched web-search call so
        # FinancialModelingAgent always receives non-null values.
        if capex_missing or opex_missing or sales_missing:
            from app.tools.web_search import estimate_budget_benchmarks

            estimates = await estimate_budget_benchmarks(
                business_description=extraction.business_description,
                geography=extraction.target_market_geography or "global",
                business_model=extraction.business_model_type or "startup",
                api_key=self._settings.tavily_api_key,
            )
            if capex_missing:
                extraction.capex_amount = estimates["capex"] or 50_000.0
            if opex_missing:
                extraction.opex_monthly_amount = estimates["opex_monthly"] or 5_000.0
            if sales_missing:
                # Conservative default: 50 units/month if web search returned no estimate
                extraction.expected_monthly_sales = estimates["monthly_sales"] or 50.0

        # ── 6. Build FeasibilityInput ─────────────────────────────────────────

        return FeasibilityInput(
            study_id=study_id,
            raw_user_input=raw_user_input,
            detected_language=lang.language_code,
            output_language=output_language,
            business_description=FieldWithSource(
                value=extraction.business_description,
                source=Source.USER_PROVIDED,
            ),
            problem_statement=FieldWithSource(
                value=extraction.problem_statement or "",
                source=_source("problem_statement", extraction.problem_statement),
            ),
            unique_value_proposition=FieldWithSource(
                value=extraction.unique_value_proposition or "",
                source=_source(
                    "unique_value_proposition", extraction.unique_value_proposition
                ),
            ),
            target_market_description=FieldWithSource(
                value=extraction.target_market_description or "",
                source=_source(
                    "target_market_description", extraction.target_market_description
                ),
            ),
            target_market_geography=FieldWithSource(
                value=extraction.target_market_geography or "",
                source=_source(
                    "target_market_geography", extraction.target_market_geography
                ),
            ),
            target_market_type=FieldWithSource(
                value=extraction.target_market_type or "",
                source=_source("target_market_type", extraction.target_market_type),
            ),
            business_model_type=FieldWithSource(
                value=extraction.business_model_type or "",
                source=_source("business_model_type", extraction.business_model_type),
            ),
            capex=FieldWithSource(
                value=extraction.capex_amount,
                source=Source.ESTIMATED if capex_missing else Source.USER_PROVIDED,
                low_confidence=capex_missing,
            ),
            capex_currency=extraction.capex_currency,
            funding_source=FieldWithSource(
                value=extraction.funding_source or "",
                source=_source("funding_source", extraction.funding_source),
            ),
            opex_monthly=FieldWithSource(
                value=extraction.opex_monthly_amount,
                source=Source.ESTIMATED if opex_missing else Source.USER_PROVIDED,
                low_confidence=opex_missing,
            ),
            opex_monthly_currency=extraction.opex_monthly_currency,
            pricing_unit_price=FieldWithSource(
                value=extraction.pricing_unit_price,
                source=Source.USER_PROVIDED,
            ),
            pricing_currency=extraction.pricing_currency,
            pricing_model=FieldWithSource(
                value=extraction.pricing_model or "",
                source=_source("pricing_model", extraction.pricing_model),
            ),
            expected_monthly_sales=FieldWithSource(
                value=extraction.expected_monthly_sales,
                source=Source.ESTIMATED if sales_missing else Source.USER_PROVIDED,
                low_confidence=sales_missing,
            ),
            competitors=[
                {"name": name, "source": Source.USER_PROVIDED}
                for name in extraction.competitors
            ],
            founder_risks=FieldWithSource(
                value=extraction.founder_risks or "",
                source=_source("founder_risks", extraction.founder_risks),
            ),
            team_size=FieldWithSource(
                value=extraction.team_size,
                source=Source.USER_PROVIDED
                if extraction.team_size is not None
                else Source.ESTIMATED,
            )
            if extraction.team_size is not None
            else None,
            key_roles_needed=FieldWithSource(
                value=extraction.key_roles_needed,
                source=_source("key_roles_needed", extraction.key_roles_needed),
            ),
            marketing_channels=FieldWithSource(
                value=extraction.marketing_channels,
                source=_source("marketing_channels", extraction.marketing_channels),
            ),
            study_goal=FieldWithSource(
                value=extraction.study_goal or "",
                source=_source("study_goal", extraction.study_goal),
            ),
            analysis_horizon_years=extraction.analysis_horizon_years,
        )
