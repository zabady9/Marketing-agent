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
        # ── 1. Language detection ──────────────────────────────────────────────
        lang = await detect_language(
            request.raw_user_input,
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
                        f"{request.raw_user_input}\n\n"
                        f"Analysis horizon: {request.analysis_horizon_years} years."
                    )
                ),
            ]
        )

        # ── 3. Apply explicit overrides from request ───────────────────────────
        if request.pricing_unit_price is not None:
            extraction.pricing_unit_price = request.pricing_unit_price
            extraction.pricing_currency = request.pricing_currency
            extraction.missing_critical_fields = [
                f for f in extraction.missing_critical_fields
                if f != "pricing_unit_price"
            ]
        if request.capex_amount is not None:
            extraction.capex_amount = request.capex_amount
            extraction.soft_missing_fields = [
                f for f in extraction.soft_missing_fields if f != "capex"
            ]
        if request.opex_monthly_amount is not None:
            extraction.opex_monthly_amount = request.opex_monthly_amount
            extraction.soft_missing_fields = [
                f for f in extraction.soft_missing_fields if f != "opex_monthly"
            ]

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
            raw_user_input=request.raw_user_input,
            detected_language=lang.language_code,
            output_language=output_language,
            business_description=FieldWithSource(
                value=extraction.business_description,
                source=Source.USER_PROVIDED,
            ),
            target_market_description=FieldWithSource(
                value=extraction.target_market_description or "",
                source=Source.USER_PROVIDED
                if extraction.target_market_description
                else Source.ESTIMATED,
            ),
            target_market_geography=FieldWithSource(
                value=extraction.target_market_geography or "",
                source=Source.USER_PROVIDED
                if extraction.target_market_geography
                else Source.ESTIMATED,
            ),
            business_model_type=FieldWithSource(
                value=extraction.business_model_type or "",
                source=Source.USER_PROVIDED
                if extraction.business_model_type
                else Source.ESTIMATED,
            ),
            capex=FieldWithSource(
                value=extraction.capex_amount,
                source=Source.ESTIMATED if capex_missing else Source.USER_PROVIDED,
                low_confidence=capex_missing,
            ),
            capex_currency=extraction.capex_currency,
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
                source=Source.USER_PROVIDED
                if extraction.pricing_model
                else Source.ESTIMATED,
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
            team_size=FieldWithSource(
                value=extraction.team_size,
                source=Source.USER_PROVIDED
                if extraction.team_size is not None
                else Source.ESTIMATED,
            )
            if extraction.team_size is not None
            else None,
            analysis_horizon_years=extraction.analysis_horizon_years,
        )
