"""
Seed a complete, realistic test workspace for manual / integration testing.

Run:
    DATABASE_URL=postgresql+asyncpg://postgres:changeme@localhost:5432/analyst \
        python scripts/seed_workspace.py

Idempotent: re-running deletes the old workspace and recreates everything from
scratch so the DB always ends up in a clean, known state.
"""

import asyncio
import sys
import uuid
from pathlib import Path

# ── make sure app/ is importable ──────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models.action_log import ActionLog
from app.models.analysis_subject import AnalysisSubject
from app.models.chat import ChatMessage, ChatSession, MessageRole
from app.models.consulting_analysis import ConsultingAnalysis
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.market_data_cache import MarketDataCache
from app.models.workspace import Workspace

# ── Fixed IDs so the seed is stable across runs ───────────────────────────────
WS_ID = "ws-test-nexaflow-001"
AS_ID = "as-test-nexaflow-001"

SESSION_A_ID = "sess-nexaflow-a"
SESSION_B_ID = "sess-nexaflow-b"

DOC_1_ID = "doc-nexaflow-pitch"
DOC_2_ID = "doc-nexaflow-competitor"

# ─────────────────────────────────────────────────────────────────────────────
# Workspace & Analysis Subject
# ─────────────────────────────────────────────────────────────────────────────

WORKSPACE = dict(
    id=WS_ID,
    name="NexaFlow Technologies",
    autonomy_level="supervised",
)

ANALYSIS_SUBJECT = dict(
    id=AS_ID,
    workspace_id=WS_ID,
    subject_name="NexaFlow Technologies",
    legal_name="NexaFlow Technologies FZ-LLC",
    subject_type="startup",
    industry="B2B SaaS / Workflow Automation",
    subject_description=(
        "NexaFlow is a Dubai-based workflow automation and analytics platform targeting "
        "mid-market companies (200-2 000 employees) across the GCC and MENA region. "
        "The platform lets non-technical operations teams build automated workflows, "
        "integrate SaaS tools, and surface real-time KPI dashboards — all without code. "
        "Founded in 2022, currently Series A ($9 M), ~45 employees."
    ),
    business_lines=[
        {
            "name": "Workflow Automation",
            "description": "No-code drag-and-drop workflow builder; triggers, conditions, actions across 200+ app integrations",
            "revenue_share": "65%",
        },
        {
            "name": "Analytics & Reporting",
            "description": "Real-time KPI dashboards, automated reports, and anomaly alerting",
            "revenue_share": "25%",
        },
        {
            "name": "Professional Services",
            "description": "Implementation, custom connector development, and training",
            "revenue_share": "10%",
        },
    ],
    tracked_competitors=[
        {
            "name": "Zapier",
            "description": "Global market leader; 7 000+ integrations; SMB-focused pricing",
            "why_relevant": "Most name-recognized alternative our prospects consider",
        },
        {
            "name": "Make.com",
            "description": "Visual scenario builder; strong in Europe; competitive on price",
            "why_relevant": "Growing fast in MENA; direct feature overlap",
        },
        {
            "name": "Microsoft Power Automate",
            "description": "Enterprise-grade; bundled with M365; deep Azure integration",
            "why_relevant": "Most GCC enterprises already have M365 — bundling risk",
        },
        {
            "name": "n8n",
            "description": "Open-source self-hosted alternative; developer-friendly",
            "why_relevant": "Attractive to price-sensitive tech-savvy buyers",
        },
    ],
    areas_of_interest=[
        "Competitive pricing strategies in GCC SaaS",
        "Enterprise procurement cycles in Saudi Arabia and UAE",
        "AI-native workflow automation trends (LLM-based triggers)",
        "Data residency compliance — UAE PDPL and Saudi NDMO requirements",
        "Go-to-market expansion: Egypt and Jordan",
    ],
    setup_status="active",
    extra={
        "founding_year": 2022,
        "hq": "Dubai, UAE",
        "funding_stage": "Series A",
        "funding_amount_usd": 9_000_000,
        "headcount": 45,
        "primary_market": "GCC + MENA",
        "pricing_model": "per-seat SaaS",
        "arr_estimate_usd": 3_200_000,
        "primary_contact": "Layla Al-Mansouri, CEO",
    },
)

# ─────────────────────────────────────────────────────────────────────────────
# Chat Sessions
# ─────────────────────────────────────────────────────────────────────────────

SESSIONS = [
    dict(
        id=SESSION_A_ID,
        workspace_id=WS_ID,
        title="SWOT Analysis Deep-Dive",
    ),
    dict(
        id=SESSION_B_ID,
        workspace_id=WS_ID,
        title="Expansion to Saudi Arabia",
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# Chat Messages  (turn_index is 1-based within a session)
# ─────────────────────────────────────────────────────────────────────────────

MESSAGES = [
    # ── Session A: SWOT deep-dive ────────────────────────────────────────────
    dict(
        id=str(uuid.uuid4()),
        session_id=SESSION_A_ID,
        workspace_id=WS_ID,
        role=MessageRole.user,
        content="Can you walk me through NexaFlow's biggest strengths and weaknesses based on what you know?",
        metadata_={},
        turn_index=1,
    ),
    dict(
        id=str(uuid.uuid4()),
        session_id=SESSION_A_ID,
        workspace_id=WS_ID,
        role=MessageRole.assistant,
        content=(
            "**Strengths**\n\n"
            "1. **MENA-first localisation**: NexaFlow is one of the few workflow automation "
            "platforms built with Arabic UI, GCC data-residency compliance (UAE PDPL, "
            "Saudi NDMO), and local payment rails (mada, UAEPAY) built in — not bolted on. "
            "This is a structural moat vs. Zapier and Make who treat the region as an afterthought.\n\n"
            "2. **Operations-team focus**: The onboarding and template library are designed "
            "for non-technical buyers. Your NPS among operations users is reportedly ~68, "
            "significantly above the SaaS median of ~35.\n\n"
            "3. **SME + mid-market sweet spot**: GCC mid-market (200–2 000 employees) is "
            "underserved by global incumbents who either price too high (Microsoft) or lack "
            "enterprise features (Zapier SMB tier).\n\n"
            "**Weaknesses**\n\n"
            "1. **Integration depth**: You have 200+ connectors vs. Zapier's 7 000+. "
            "Enterprise buyers with complex stacks hit gaps quickly, especially around "
            "niche ERP systems (SAP MENA flavors, Oracle Fusion GCC).\n\n"
            "2. **Brand awareness**: Outside Dubai, brand recognition is near zero. "
            "Saudi and Egyptian prospects in our research consistently said they hadn't "
            "heard of NexaFlow before the sales intro.\n\n"
            "3. **Single-region engineering talent**: All R&D is in Dubai. "
            "Competing for talent against hyperscalers paying FAANG-equivalent packages "
            "creates retention risk.\n\n"
            "Want me to run a full cited SWOT analysis with market data?"
        ),
        metadata_={"sources_used": 3, "agent": "consulting"},
        turn_index=2,
    ),
    dict(
        id=str(uuid.uuid4()),
        session_id=SESSION_A_ID,
        workspace_id=WS_ID,
        role=MessageRole.user,
        content="Yes, please run the full SWOT. Focus especially on the threats from Microsoft Power Automate.",
        metadata_={},
        turn_index=3,
    ),
    dict(
        id=str(uuid.uuid4()),
        session_id=SESSION_A_ID,
        workspace_id=WS_ID,
        role=MessageRole.assistant,
        content=(
            "I've triggered the full cited SWOT analysis. It's currently running in the background "
            "and should complete in 2–3 minutes.\n\n"
            "**On the Microsoft Power Automate threat specifically:**\n\n"
            "The bundling risk is real but more nuanced than it first appears:\n\n"
            "- **Who it affects**: Enterprises already on M365 E3/E5. In Saudi Arabia, "
            "government and quasi-government entities (SOEs) represent ~40% of enterprise "
            "software spend — and most already have M365 deals. These are the hardest "
            "accounts for NexaFlow to win.\n\n"
            "- **Power Automate's ceiling**: Microsoft's strength is within the M365 ecosystem. "
            "Cross-platform automation (e.g., connecting a local Saudi ERP to a WhatsApp "
            "Business API to a local payment gateway) is still clunky. NexaFlow's MENA "
            "connector library wins here.\n\n"
            "- **Price position**: Power Automate per-user plans run $15–$40/user/month. "
            "If bundled, effective cost to buyer is near zero — this is the genuine danger. "
            "Counter-strategy: price below the noise floor for SMEs, and differentiate "
            "on MENA-native features that Power Automate doesn't prioritise.\n\n"
            "The full SWOT analysis will have citations and confidence scores for each point."
        ),
        metadata_={"sources_used": 5, "agent": "consulting", "analysis_triggered": True},
        turn_index=4,
    ),

    # ── Session B: Saudi expansion ───────────────────────────────────────────
    dict(
        id=str(uuid.uuid4()),
        session_id=SESSION_B_ID,
        workspace_id=WS_ID,
        role=MessageRole.user,
        content="We're planning to expand into Saudi Arabia in Q1 2025. What should we prioritize?",
        metadata_={},
        turn_index=1,
    ),
    dict(
        id=str(uuid.uuid4()),
        session_id=SESSION_B_ID,
        workspace_id=WS_ID,
        role=MessageRole.assistant,
        content=(
            "Saudi Arabia is NexaFlow's highest-potential expansion market, but also the "
            "most compliance-heavy. Here's what to prioritise, in order:\n\n"
            "**1. NDMO Cloud Residency Certification (Month 1–2)**\n"
            "Saudi Arabia's National Data Management Office requires that data classified "
            "as 'national' or 'sensitive' be stored on Saudi-resident cloud infrastructure. "
            "Without this, you're locked out of government, banking, and telecom buyers "
            "(which is ~60% of addressable enterprise spend in KSA). "
            "Fastest path: deploy on Alibaba Cloud KSA or AWS Riyadh region and get "
            "NDMO certification.\n\n"
            "**2. Local Entity (Month 1–3)**\n"
            "Selling B2B SaaS to Saudi enterprises typically requires a local entity "
            "(Saudi Arabia or a GCC free zone with KSA commercial registration). "
            "Consider NEOM Tech & Digital Company or a Riyadh-based entity under Vision 2030 "
            "tech incentives — up to 30% cost subsidies available.\n\n"
            "**3. Arabic-First UI Review (Month 1)**\n"
            "Your existing Arabic UI has gaps in RTL layout for complex workflow diagrams. "
            "Saudi users rate Arabic UI quality higher than UAE users — fix this before launch.\n\n"
            "**4. Partner with a local VAR (Month 2–4)**\n"
            "Direct sales into Saudi enterprise is slow without a local Value-Added Reseller "
            "relationship. Target VARs already serving Tier-2 Saudi banks and manufacturing "
            "companies.\n\n"
            "Want me to run a full market feasibility analysis for the KSA expansion?"
        ),
        metadata_={"sources_used": 7, "agent": "consulting"},
        turn_index=2,
    ),
    dict(
        id=str(uuid.uuid4()),
        session_id=SESSION_B_ID,
        workspace_id=WS_ID,
        role=MessageRole.user,
        content="What's the realistic ARR opportunity in Saudi Arabia in year 1?",
        metadata_={},
        turn_index=3,
    ),
    dict(
        id=str(uuid.uuid4()),
        session_id=SESSION_B_ID,
        workspace_id=WS_ID,
        role=MessageRole.assistant,
        content=(
            "**Year 1 KSA ARR Estimate: $600K–$1.2M** (base case: $850K)\n\n"
            "Here's the bottom-up model:\n\n"
            "| Segment | Accounts | ACV | ARR |\n"
            "|---------|----------|-----|-----|\n"
            "| Mid-market (200–500 employees) | 8–12 | $24K | $240K |\n"
            "| Upper mid-market (500–2K employees) | 4–6 | $60K | $300K |\n"
            "| Pilot / land-and-expand accounts | 6–10 | $15K | $120K |\n"
            "| **Total** | **18–28** | — | **$660K–$1.1M** |\n\n"
            "**Key assumptions:**\n"
            "- Sales cycle: 3–5 months for mid-market (slower than UAE due to procurement)\n"
            "- 1 dedicated KSA AE hired by Month 2\n"
            "- Partner channel (VAR) contributes ~30% of deals\n"
            "- NDMO certification complete by end of Month 2\n\n"
            "**Risk factors that could compress this:**\n"
            "- NDMO certification delays (2–3 months worst case)\n"
            "- Microsoft Power Automate bundling deals in target accounts\n"
            "- Hiring a strong local AE (competitive market)\n\n"
            "This is conservative vs. NexaFlow's UAE trajectory but realistic given the "
            "compliance and relationship-building time required."
        ),
        metadata_={"sources_used": 4, "agent": "consulting", "has_table": True},
        turn_index=4,
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# Consulting Analyses
# ─────────────────────────────────────────────────────────────────────────────

ANALYSES = [
    dict(
        id="ca-nexaflow-swot-001",
        workspace_id=WS_ID,
        analysis_type="swot",
        status="completed",
        chat_message_id=None,
        results={
            "citations": [
                {"title": "GCC SaaS Market Report 2024", "url": "https://example.com/gcc-saas-2024", "snippet": "GCC SaaS market to reach $4.2B by 2026, growing at 18% CAGR"},
                {"title": "Microsoft Power Automate KSA Pricing", "url": "https://example.com/pa-pricing", "snippet": "Power Automate per-user plan $15/month when not bundled"},
                {"title": "UAE PDPL Compliance Guide", "url": "https://example.com/pdpl", "snippet": "Personal Data Protection Law requires data residency for national data"},
                {"title": "Zapier 2024 Partner Report", "url": "https://example.com/zapier-partners", "snippet": "Zapier reports 7,000+ integrations, primarily US and EU focused"},
                {"title": "MENA Startup Ecosystem 2024", "url": "https://example.com/mena-startups", "snippet": "Dubai remains #1 tech hub; Series A rounds averaging $8-12M in 2024"},
            ],
            "swot": {
                "strengths": [
                    {
                        "point": "MENA-native compliance (UAE PDPL, Saudi NDMO) built into core product",
                        "evidence": "NexaFlow stores all data in UAE or KSA clouds by default; competitors require manual configuration",
                        "citation_indices": [2],
                        "unverified": False,
                    },
                    {
                        "point": "Arabic-first UI with RTL layout across all features",
                        "evidence": "Only workflow automation platform in the GCC with fully native Arabic interface",
                        "citation_indices": [],
                        "unverified": False,
                    },
                    {
                        "point": "Strong NPS (~68) among non-technical operations teams",
                        "evidence": "Internal NPS data Q3 2024; significantly above SaaS median of ~35",
                        "citation_indices": [],
                        "unverified": True,
                    },
                ],
                "weaknesses": [
                    {
                        "point": "Integration library (200+) dwarfed by Zapier (7,000+)",
                        "evidence": "Zapier 2024 Partner Report confirms 7,000+ live integrations",
                        "citation_indices": [3],
                        "unverified": False,
                    },
                    {
                        "point": "Low brand awareness outside Dubai",
                        "evidence": "Sales team feedback: Saudi and Egyptian prospects consistently unaware of NexaFlow pre-introduction",
                        "citation_indices": [],
                        "unverified": True,
                    },
                ],
                "opportunities": [
                    {
                        "point": "GCC SaaS market growing 18% CAGR through 2026",
                        "evidence": "GCC SaaS Market Report 2024 projects $4.2B market by 2026",
                        "citation_indices": [0],
                        "unverified": False,
                    },
                    {
                        "point": "Vision 2030 digital transformation mandates creating demand",
                        "evidence": "Saudi government mandating digitisation of all government services by 2025",
                        "citation_indices": [],
                        "unverified": False,
                    },
                ],
                "threats": [
                    {
                        "point": "Microsoft Power Automate bundled with M365 at near-zero marginal cost to buyers",
                        "evidence": "Power Automate per-user plan at $15/month when unbundled; effectively free with E3/E5",
                        "citation_indices": [1],
                        "unverified": False,
                    },
                    {
                        "point": "Make.com accelerating MENA expansion with localised go-to-market",
                        "evidence": "Make.com opened Dubai office Q2 2024 and hired 3 regional AEs",
                        "citation_indices": [],
                        "unverified": True,
                    },
                ],
            },
        },
    ),
    dict(
        id="ca-nexaflow-pestel-001",
        workspace_id=WS_ID,
        analysis_type="pestel",
        status="completed",
        chat_message_id=None,
        results={
            "citations": [
                {"title": "UAE Digital Economy Strategy 2031", "url": "https://example.com/uae-digital", "snippet": "UAE targets 19.4% of GDP from digital economy by 2031"},
                {"title": "Saudi Vision 2030 Tech Pillar", "url": "https://example.com/ksa-vision", "snippet": "KSA investing $18B in digital infrastructure 2024-2026"},
                {"title": "GCC AI Regulatory Landscape", "url": "https://example.com/gcc-ai-reg", "snippet": "UAE and KSA publishing AI ethics frameworks; enforcement light in 2024"},
            ],
            "pestel": {
                "political": [
                    {
                        "factor": "Government digitisation mandates",
                        "observation": "UAE and KSA governments are mandating digital transformation of public services",
                        "implication": "Creates pipeline of government and SOE automation projects",
                        "citation_indices": [0, 1],
                        "unverified": False,
                    }
                ],
                "economical": [
                    {
                        "factor": "Oil price dependency of GCC economies",
                        "observation": "GCC IT budgets correlate ~0.6 with Brent crude; current price ~$82/barrel",
                        "implication": "Moderate budget risk; current price supports healthy IT spend",
                        "citation_indices": [],
                        "unverified": False,
                    }
                ],
                "social": [
                    {
                        "factor": "Young, tech-literate workforce",
                        "observation": "Median age in UAE is 33; KSA 29. High smartphone penetration (>95%)",
                        "implication": "Buyers are comfortable with SaaS tools and expect modern UX",
                        "citation_indices": [],
                        "unverified": False,
                    }
                ],
                "technological": [
                    {
                        "factor": "LLM-native workflow automation trend",
                        "observation": "Zapier, Make, and n8n all shipped AI-step features in 2024",
                        "implication": "NexaFlow needs AI-step roadmap within 12 months to stay competitive",
                        "citation_indices": [],
                        "unverified": False,
                    }
                ],
                "environmental": [
                    {
                        "factor": "Regional sustainability mandates",
                        "observation": "UAE Net Zero 2050 and KSA Net Zero 2060 creating ESG reporting requirements",
                        "implication": "Opportunity to build ESG data automation workflows as a product line",
                        "citation_indices": [],
                        "unverified": True,
                    }
                ],
                "legal": [
                    {
                        "factor": "UAE PDPL and Saudi NDMO data residency laws",
                        "observation": "Both laws require sensitive/national data to remain in-country",
                        "implication": "NexaFlow's local-first infra is a compliance moat; must be maintained as regulations evolve",
                        "citation_indices": [2],
                        "unverified": False,
                    }
                ],
            },
        },
    ),
    dict(
        id="ca-nexaflow-feasibility-001",
        workspace_id=WS_ID,
        analysis_type="feasibility",
        status="generating",
        chat_message_id=None,
        results=None,
        error=None,
    ),
    dict(
        id="ca-nexaflow-market-001",
        workspace_id=WS_ID,
        analysis_type="market_research",
        status="completed",
        chat_message_id=None,
        results={
            "citations": [
                {"title": "IDC GCC SaaS Forecast 2024", "url": "https://example.com/idc-gcc", "snippet": "GCC SaaS market $2.1B in 2023, forecast $4.2B by 2026"},
                {"title": "Workflow Automation TAM Analysis", "url": "https://example.com/wfa-tam", "snippet": "Global workflow automation market $26B in 2024, 23% CAGR"},
            ],
            "market_overview": {
                "title": "GCC Workflow Automation Market",
                "findings": [
                    "Total Addressable Market (GCC): $340M in 2024, growing to $620M by 2027",
                    "Mid-market segment (200-2,000 employees) represents ~45% of TAM",
                    "UAE accounts for ~38% of GCC SaaS spend; Saudi Arabia ~44%; rest of GCC ~18%",
                    "Average contract value for mid-market automation: $18K–$65K ACV",
                ],
                "citation_indices": [0, 1],
                "unverified": False,
            },
            "segments": [
                {
                    "segment_name": "Government & SOEs",
                    "size_estimate": "$95M TAM (GCC)",
                    "growth_trend": "22% CAGR — Vision 2030 and UAE 2031 driving mandated digitisation",
                    "key_players": ["Microsoft Power Automate", "SAP BTP", "Oracle Integration Cloud"],
                    "citation_indices": [0],
                    "unverified": False,
                },
                {
                    "segment_name": "Financial Services",
                    "size_estimate": "$75M TAM (GCC)",
                    "growth_trend": "18% CAGR — compliance automation and digital banking transformation",
                    "key_players": ["Zapier", "Make.com", "MuleSoft"],
                    "citation_indices": [],
                    "unverified": False,
                },
                {
                    "segment_name": "Retail & E-Commerce",
                    "size_estimate": "$55M TAM (GCC)",
                    "growth_trend": "25% CAGR — fastest growing; post-COVID omnichannel investment",
                    "key_players": ["Zapier", "n8n", "Shopify Flow (in-platform)"],
                    "citation_indices": [],
                    "unverified": False,
                },
            ],
            "key_trends": [
                {
                    "point": "AI-native automation (LLM-based decision steps) becoming table stakes",
                    "evidence": "All top 5 competitors shipped AI-step features in 2024",
                    "citation_indices": [],
                    "unverified": False,
                }
            ],
            "competitive_dynamics": [
                {
                    "point": "Zapier dominates SMB; Microsoft dominates enterprise; mid-market is contested",
                    "evidence": "Market share estimates: Zapier 28%, Microsoft 22%, Make 14%, others 36%",
                    "citation_indices": [1],
                    "unverified": True,
                }
            ],
            "strategic_implications": (
                "NexaFlow's optimal beachhead is GCC mid-market retail and financial services — "
                "segments where MENA compliance matters, global players under-serve, and budgets are healthy. "
                "Government/SOE is high-value but procurement is slow; pursue in parallel with a dedicated "
                "public-sector motion after KSA entity is established."
            ),
        },
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# Market Data Cache (competitor data)
# ─────────────────────────────────────────────────────────────────────────────

MARKET_DATA = [
    # Zapier
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        competitor_name="zapier",
        metric_type="revenue",
        value={"amount": 140_000_000, "currency": "USD", "period": "2023 estimated ARR", "confidence": "medium"},
        source_url="https://example.com/zapier-revenue-2023",
        source_title="Zapier Revenue Estimates 2023 — SaaSOptics",
        ttl_hours=720,
    ),
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        competitor_name="zapier",
        metric_type="headcount",
        value={"count": 900, "source_date": "2024-Q1", "confidence": "high"},
        source_url="https://example.com/zapier-headcount",
        source_title="Zapier LinkedIn headcount data",
        ttl_hours=168,
    ),
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        competitor_name="zapier",
        metric_type="pricing",
        value={
            "plans": [
                {"name": "Free", "price_usd": 0, "tasks_per_month": 100},
                {"name": "Starter", "price_usd": 19.99, "tasks_per_month": 750},
                {"name": "Professional", "price_usd": 49, "tasks_per_month": 2000},
                {"name": "Team", "price_usd": 69, "tasks_per_month": 2000},
                {"name": "Enterprise", "price_usd": None, "tasks_per_month": "unlimited"},
            ],
            "currency": "USD",
            "billing": "monthly",
        },
        source_url="https://example.com/zapier-pricing",
        source_title="Zapier Pricing Page",
        ttl_hours=168,
    ),
    # Make.com
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        competitor_name="make.com",
        metric_type="funding",
        value={"total_raised_usd": 100_000_000, "last_round": "Series B", "last_round_year": 2021, "investors": ["Celonis", "General Catalyst"], "confidence": "high"},
        source_url="https://example.com/make-funding",
        source_title="Make.com Series B Announcement",
        ttl_hours=720,
    ),
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        competitor_name="make.com",
        metric_type="pricing",
        value={
            "plans": [
                {"name": "Free", "price_usd": 0, "ops_per_month": 1000},
                {"name": "Core", "price_usd": 9, "ops_per_month": 10000},
                {"name": "Pro", "price_usd": 16, "ops_per_month": 10000},
                {"name": "Teams", "price_usd": 29, "ops_per_month": 10000},
                {"name": "Enterprise", "price_usd": None, "ops_per_month": "unlimited"},
            ],
            "currency": "USD",
            "billing": "monthly",
        },
        source_url="https://example.com/make-pricing",
        source_title="Make.com Pricing Page",
        ttl_hours=168,
    ),
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        competitor_name="make.com",
        metric_type="news_sentiment",
        value={
            "summary": "Make.com opened a Dubai office in Q2 2024 and is actively hiring MENA sales reps. Positive press around their Arabic interface launch in June 2024.",
            "sentiment": "positive",
            "articles": [
                {"title": "Make.com eyes MENA growth with Dubai office", "date": "2024-04-15"},
                {"title": "Make.com launches Arabic interface", "date": "2024-06-02"},
            ],
        },
        source_url="https://example.com/make-mena-expansion",
        source_title="Make.com MENA expansion news compilation",
        ttl_hours=24,
    ),
    # Microsoft Power Automate
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        competitor_name="microsoft power automate",
        metric_type="market_share",
        value={
            "global_share_pct": 22,
            "gcc_enterprise_share_pct": 38,
            "methodology": "Gartner 2024 Magic Quadrant for iPaaS",
            "confidence": "high",
        },
        source_url="https://example.com/gartner-ipaas-2024",
        source_title="Gartner Magic Quadrant for iPaaS 2024",
        ttl_hours=168,
    ),
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        competitor_name="microsoft power automate",
        metric_type="pricing",
        value={
            "plans": [
                {"name": "Power Automate Premium", "price_usd": 15, "unit": "per user/month"},
                {"name": "Power Automate Process", "price_usd": 150, "unit": "per bot/month"},
                {"name": "Included in M365 E3", "price_usd": 0, "note": "limited version bundled"},
                {"name": "Included in M365 E5", "price_usd": 0, "note": "premium version bundled"},
            ],
            "currency": "USD",
            "key_risk": "Near-zero marginal cost when bundled with existing M365 enterprise agreements",
        },
        source_url="https://example.com/pa-pricing-2024",
        source_title="Microsoft Power Automate Pricing 2024",
        ttl_hours=168,
    ),
    # n8n
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        competitor_name="n8n",
        metric_type="funding",
        value={"total_raised_usd": 55_000_000, "last_round": "Series B", "last_round_year": 2023, "investors": ["Sequoia", "Felicis"], "confidence": "high"},
        source_url="https://example.com/n8n-funding",
        source_title="n8n Series B press release",
        ttl_hours=720,
    ),
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        competitor_name="n8n",
        metric_type="pricing",
        value={
            "plans": [
                {"name": "Starter", "price_usd": 20, "unit": "per user/month"},
                {"name": "Pro", "price_usd": 50, "unit": "per user/month"},
                {"name": "Enterprise", "price_usd": None, "unit": "custom"},
                {"name": "Self-hosted", "price_usd": 0, "note": "open source, self-managed infra costs only"},
            ],
            "currency": "USD",
            "key_differentiator": "Open-source self-hosted option removes vendor lock-in concern",
        },
        source_url="https://example.com/n8n-pricing",
        source_title="n8n Cloud Pricing",
        ttl_hours=168,
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Documents & Chunks
# ─────────────────────────────────────────────────────────────────────────────

DOCUMENTS = [
    dict(
        id=DOC_1_ID,
        workspace_id=WS_ID,
        filename="NexaFlow_Pitch_Deck_Series_A.pdf",
        doc_type="pitch_deck",
        storage_path=f"/app/uploads/{WS_ID}/NexaFlow_Pitch_Deck_Series_A.pdf",
        status="indexed",
    ),
    dict(
        id=DOC_2_ID,
        workspace_id=WS_ID,
        filename="Competitor_Analysis_Q4_2024.pdf",
        doc_type="competitive_intelligence",
        storage_path=f"/app/uploads/{WS_ID}/Competitor_Analysis_Q4_2024.pdf",
        status="indexed",
    ),
]

CHUNKS = [
    # Pitch deck chunks
    dict(
        id=str(uuid.uuid4()),
        document_id=DOC_1_ID,
        workspace_id=WS_ID,
        content=(
            "NexaFlow Technologies — Series A Pitch Deck\n\n"
            "The Problem: 73% of GCC mid-market companies still rely on manual, "
            "spreadsheet-driven operations workflows. Cross-system automation tools "
            "either don't support Arabic, lack MENA compliance (PDPL/NDMO), or are "
            "priced for Silicon Valley startups — not regional mid-market. "
            "The result: operations teams waste 12+ hours/week on manual data transfer "
            "and status updates. That's $4,200/employee/year in lost productivity."
        ),
        metadata_={"page": 3, "section": "Problem Statement"},
    ),
    dict(
        id=str(uuid.uuid4()),
        document_id=DOC_1_ID,
        workspace_id=WS_ID,
        content=(
            "NexaFlow Solution: A no-code workflow automation platform built for MENA.\n\n"
            "Key differentiators:\n"
            "1. Arabic-first UI — full RTL, native Arabic documentation\n"
            "2. MENA compliance-ready — UAE PDPL and Saudi NDMO data residency out of the box\n"
            "3. Local integrations — WhatsApp Business, mada, UAEPAY, local ERP connectors\n"
            "4. Ops-team onboarding in <1 day (vs. 2-3 weeks for enterprise competitors)\n\n"
            "Current traction: 87 paying customers, $3.2M ARR, 127% net revenue retention."
        ),
        metadata_={"page": 5, "section": "Solution & Traction"},
    ),
    dict(
        id=str(uuid.uuid4()),
        document_id=DOC_1_ID,
        workspace_id=WS_ID,
        content=(
            "Go-to-Market Strategy\n\n"
            "Phase 1 (2022-2024): UAE beachhead — target Dubai/Abu Dhabi mid-market retail "
            "and fintech. Land via outbound + LinkedIn.\n\n"
            "Phase 2 (2025): Saudi Arabia expansion — entity in Riyadh, NDMO certification, "
            "partner with 2 local VARs. Target 20 KSA logos in first 12 months.\n\n"
            "Phase 3 (2026): Pan-GCC + Egypt — leverage KSA case studies for Kuwait, Qatar, Bahrain.\n\n"
            "Unit economics: CAC $8,200 | LTV $94,000 | LTV:CAC 11.5x | Payback period 14 months."
        ),
        metadata_={"page": 8, "section": "Go-to-Market"},
    ),
    # Competitor analysis chunks
    dict(
        id=str(uuid.uuid4()),
        document_id=DOC_2_ID,
        workspace_id=WS_ID,
        content=(
            "Competitor Analysis: Zapier in MENA (Q4 2024)\n\n"
            "Zapier's MENA presence remains minimal. Key findings:\n"
            "- No Arabic language support as of Q4 2024\n"
            "- No data residency options for UAE or Saudi Arabia\n"
            "- No dedicated MENA sales or support team\n"
            "- Pricing in USD only; no local payment methods\n\n"
            "Despite these gaps, Zapier wins deals in MENA when: (1) buyer is a regional "
            "office of a global company already on Zapier, (2) buyer is a tech-forward "
            "startup with English-only operations, or (3) the use case is simple (2-3 step "
            "workflows) where Zapier's brand recognition closes the deal."
        ),
        metadata_={"page": 2, "section": "Zapier Analysis"},
    ),
    dict(
        id=str(uuid.uuid4()),
        document_id=DOC_2_ID,
        workspace_id=WS_ID,
        content=(
            "Competitor Analysis: Make.com in MENA (Q4 2024)\n\n"
            "Make.com is NexaFlow's most dangerous near-term competitive threat. Changes in 2024:\n"
            "- Opened Dubai office (April 2024), hired 3 MENA AEs\n"
            "- Launched Arabic interface (June 2024) — partial, not full RTL\n"
            "- Closed 3 known GCC enterprise deals in H2 2024\n"
            "- Pricing 40% below NexaFlow equivalent tier\n\n"
            "Make's weaknesses in MENA: still no PDPL/NDMO compliance, no local payment "
            "integrations (mada, UAEPAY), and Arabic UI is incomplete. "
            "However, they are moving fast — assume full MENA feature parity by Q3 2025."
        ),
        metadata_={"page": 4, "section": "Make.com Analysis"},
    ),
    dict(
        id=str(uuid.uuid4()),
        document_id=DOC_2_ID,
        workspace_id=WS_ID,
        content=(
            "Competitive Positioning Recommendation (Q4 2024)\n\n"
            "NexaFlow should double down on compliance and local integrations as primary "
            "differentiation — this is a 12-18 month moat before competitors catch up.\n\n"
            "Priority actions:\n"
            "1. Get NDMO certification for Saudi data residency (Q1 2025)\n"
            "2. Expand local connector library to 50 MENA-specific integrations (Q2 2025)\n"
            "3. Launch 'Compliance Badge' marketing campaign to drive awareness of PDPL/NDMO readiness\n"
            "4. Price defensively vs. Make.com — match on entry tier, win on features\n\n"
            "Long-term: invest in AI-step features (LLM-based conditions and actions) to "
            "avoid commoditisation. Zapier and Make are shipping these; NexaFlow needs "
            "parity by Q3 2025 to avoid churn from tech-forward customers."
        ),
        metadata_={"page": 12, "section": "Strategic Recommendations"},
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# Action Logs
# ─────────────────────────────────────────────────────────────────────────────

ACTION_LOGS = [
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        actor="system",
        action="analysis_subject.upserted",
        payload={"subject_name": "NexaFlow Technologies", "setup_status": "active"},
        result={"success": True},
    ),
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        actor="system",
        action="consulting_analysis.started",
        payload={"analysis_type": "swot", "analysis_id": "ca-nexaflow-swot-001"},
        result=None,
    ),
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        actor="system",
        action="consulting_analysis.completed",
        payload={"analysis_type": "swot", "analysis_id": "ca-nexaflow-swot-001"},
        result={"duration_seconds": 47, "citations_found": 5},
    ),
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        actor="system",
        action="consulting_analysis.completed",
        payload={"analysis_type": "pestel", "analysis_id": "ca-nexaflow-pestel-001"},
        result={"duration_seconds": 62, "citations_found": 3},
    ),
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        actor="system",
        action="knowledge.document_indexed",
        payload={"document_id": DOC_1_ID, "filename": "NexaFlow_Pitch_Deck_Series_A.pdf", "chunks_created": 3},
        result={"success": True},
    ),
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        actor="system",
        action="knowledge.document_indexed",
        payload={"document_id": DOC_2_ID, "filename": "Competitor_Analysis_Q4_2024.pdf", "chunks_created": 3},
        result={"success": True},
    ),
    dict(
        id=str(uuid.uuid4()),
        workspace_id=WS_ID,
        actor="user",
        action="chat.message_sent",
        payload={"session_id": SESSION_A_ID, "content_length": 87},
        result=None,
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Seed runner
# ─────────────────────────────────────────────────────────────────────────────

async def seed():
    async with AsyncSessionLocal() as db:
        print("🗑️  Deleting existing test workspace if present...")
        # Cascade deletes handle children via FK; ActionLog has no FK so delete manually
        await db.execute(delete(ActionLog).where(ActionLog.workspace_id == WS_ID))
        existing_ws = await db.get(Workspace, WS_ID)
        if existing_ws:
            await db.delete(existing_ws)
            await db.flush()

        print("🏢  Creating workspace...")
        db.add(Workspace(**WORKSPACE))
        await db.flush()  # workspace must exist before FK children

        print("📋  Creating analysis subject...")
        db.add(AnalysisSubject(**ANALYSIS_SUBJECT))

        print("💬  Creating chat sessions...")
        for s in SESSIONS:
            db.add(ChatSession(**s))
        await db.flush()  # sessions must exist before messages

        print("   Adding messages...")
        for m in MESSAGES:
            db.add(ChatMessage(**m))

        print("🔬  Creating consulting analyses...")
        for a in ANALYSES:
            db.add(ConsultingAnalysis(**a))

        print("📊  Creating market data cache...")
        for md in MARKET_DATA:
            db.add(MarketDataCache(**md))

        print("📄  Creating knowledge documents...")
        for doc in DOCUMENTS:
            db.add(KnowledgeDocument(**doc))
        await db.flush()  # docs must exist before chunks

        print("   Adding knowledge chunks...")
        for chunk in CHUNKS:
            db.add(KnowledgeChunk(**chunk))

        print("📝  Creating action logs...")
        for log in ACTION_LOGS:
            db.add(ActionLog(**log))

        await db.commit()

    print("\n✅  Seed complete!")
    print(f"   Workspace ID  : {WS_ID}")
    print(f"   Workspace name: NexaFlow Technologies")
    print(f"   Chat sessions : {len(SESSIONS)} ({SESSION_A_ID}, {SESSION_B_ID})")
    print(f"   Messages      : {len(MESSAGES)}")
    print(f"   Analyses      : {len(ANALYSES)} (swot✓ pestel✓ feasibility⏳ market_research✓)")
    print(f"   Competitors   : {len(MARKET_DATA)} market data rows")
    print(f"   Knowledge docs: {len(DOCUMENTS)} ({len(CHUNKS)} chunks)")
    print(f"   Action logs   : {len(ACTION_LOGS)}")


if __name__ == "__main__":
    asyncio.run(seed())
