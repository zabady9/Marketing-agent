# Consulting Endpoint — Eval Context

This document captures all context needed to design test scenarios evaluating the response quality of the `/consult` and `/analyses` endpoints. It is intended for anyone writing new eval scenarios and should be updated whenever the intent prompt, output schemas, or eval rubric changes.

---

## 1. Purpose & Scope

### What the bot does

The consulting endpoint takes a free-text business question and a pre-configured brand profile and produces a structured strategic analysis grounded in live web research. It covers five analysis types:

| Type | Description |
|---|---|
| `swot` | Strengths, Weaknesses, Opportunities, Threats |
| `pestel` | Macro-environment (Political, Economic, Social, Technological, Environmental, Legal) |
| `feasibility` | Go/no-go study: market size, competition, target customer, risks, recommendation |
| `brand_analysis` | Positioning, messaging clarity, audience alignment |
| `market_research` | Market segments, consumer trends, competitive landscape |

Every output item includes a text claim, a one-sentence evidence rationale, and integer citation indices pointing into a deduped source list (max 15 sources, min 4 required). A built-in eval agent scores each completed report automatically.

### Target user

Business owners and marketing teams who have already created a Workspace and completed the Brand Profile onboarding. They expect analyst-quality strategic output, not general-purpose chat. They are the primary decision-maker for the brand being analysed.

### What it should NOT handle

- Social media content creation, post writing, copywriting
- Personal advice unrelated to the business
- Generic or exploratory questions that do not resolve to a specific analysis type
- HR, finance, or operational questions outside strategic business consulting scope

---

## 2. Intent Routing Logic

The `/consult` endpoint runs a dedicated intent classification step before any analysis is started.

**Classifier model:** `gemini-2.5-flash` via `with_structured_output` (JSON schema mode).

**Input to classifier:** the raw `question` string + `brand_name` and `industry` from the brand profile.

**Seven possible outputs:**

| `analysis_type` | Meaning | HTTP result |
|---|---|---|
| `swot` | SWOT analysis | 202 (job queued) |
| `pestel` | PESTEL analysis | 202 (job queued) |
| `feasibility` | Feasibility study | 202 (job queued) |
| `brand_analysis` | Brand assessment | 202 (job queued) |
| `market_research` | Market landscape | 202 (job queued) |
| `general` | Genuinely ambiguous across ≥2 types equally | 422 with clarifying question in `detail.message` |
| `out_of_scope` | Not a strategic business question | 422 with polite decline in `detail.message` |

**Key classifier rule:** "Be decisive. Only classify as `general` if the question truly maps equally to multiple types with no clear primary." This means in practice `general` is rare — a question like _"Tell me about the market and our competition"_ may be classified as `market_research` rather than `general`. This is a documented known risk (see §4).

**Bypass:** The `/analyses:generate` endpoint skips classification entirely and accepts `analysis_type` directly as a Pydantic `Literal`. It accepts only the five actionable types; passing `"general"` or `"out_of_scope"` returns 422 from Pydantic validation.

---

## 3. Input / Output Contract

### Requests

**Option A — NL intent routing** (`/consult`):
```
POST /api/workspaces/{workspace_id}/consult
Content-Type: application/json

{ "question": "What are our biggest weaknesses versus competitors?" }
```

**Option B — explicit type** (`/analyses:generate`):
```
POST /api/workspaces/{workspace_id}/analyses:generate
Content-Type: application/json

{
  "analysis_type": "swot",        // required: swot | pestel | feasibility | brand_analysis | market_research
  "context": "optional free text" // optional: extra context, silently truncated to 200 chars in queries
}
```

Both require the workspace to exist and have a brand profile set.

### Immediate response (202)

Both endpoints return **202 immediately** — the analysis runs in a background task:
```json
{
  "id": "uuid",
  "workspace_id": "uuid",
  "analysis_type": "swot",
  "status": "generating",
  "results": null,
  "error": null,
  "created_at": "2026-08-03T...",
  "classified_as": "swot"   // /consult only; absent from /analyses:generate
}
```

### Error responses

| Status | When |
|---|---|
| 404 | workspace not found |
| 422 | brand profile not set; `general`/`out_of_scope` classification; invalid `analysis_type` value |
| 503 | Gemini LLM unreachable during classification |

For non-actionable classifications (422), the body is:
```json
{
  "detail": {
    "classification": "out_of_scope",
    "message": "This platform handles strategic analysis. Try asking about market research."
  }
}
```

### Polling for completion

```
GET /api/workspaces/{workspace_id}/analyses/{analysis_id}
```
Poll until `status != "generating"`. Final states: `"ready"` or `"failed"`.

### Completed analysis response (`status: "ready"`)

`results` is a JSON object:
```json
{
  "analysis_type": "swot",
  "output": { ... },          // type-specific structure (see below)
  "citations": [              // list of up to 15 sources
    { "title": "...", "url": "...", "snippet": "..." }
  ],
  "disclaimer": "هذا التحليل مُولَّد بالذكاء الاصطناعي...",  // Arabic disclaimer, always present
  "eval": { ... }             // EvalOutput (see §5), may be null if eval threw
}
```

### Output structures by type

**SWOT:**
```json
{
  "strengths":     [{ "point": "...", "evidence": "...", "citation_indices": [0,2], "unverified": false }],
  "weaknesses":    [ ... ],
  "opportunities": [ ... ],
  "threats":       [ ... ]
}
```

**PESTEL:**
```json
{
  "political":     [{ "factor": "...", "observation": "...", "implication": "...", "citation_indices": [1], "unverified": false }],
  "economical":    [ ... ],
  "social":        [ ... ],
  "technological": [ ... ],
  "environmental": [ ... ],
  "legal":         [ ... ]
}
```

**Feasibility:**
```json
{
  "market_size_and_growth":  { "title": "...", "findings": ["..."], "citation_indices": [0], "unverified": false },
  "competitive_landscape":   { ... },
  "target_customer":         { ... },
  "key_risks":               { ... },
  "recommendation":          "proceed_with_caution",  // one of: proceed | proceed_with_caution | do_not_proceed
  "recommendation_rationale": "..."
}
```

**Brand Analysis:**
```json
{
  "positioning":       [{ "dimension": "...", "current_state": "...", "gap_or_strength": "...", "recommendation": "...", "citation_indices": [3], "unverified": false }],
  "messaging":         [ ... ],
  "audience_alignment":[ ... ],
  "summary_recommendation": "..."
}
```

**Market Research:**
```json
{
  "market_overview":       { "title": "...", "findings": ["..."], "citation_indices": [0], "unverified": false },
  "segments":              [{ "segment_name": "...", "size_estimate": "...", "growth_trend": "...", "key_players": ["..."], "citation_indices": [1] }],
  "key_trends":            [{ "point": "...", "evidence": "...", "citation_indices": [2] }],
  "competitive_dynamics":  [{ "point": "...", "evidence": "...", "citation_indices": [3] }],
  "strategic_implications": "..."
}
```

### SSE streaming

```
GET /api/workspaces/{workspace_id}/analyses/{analysis_id}/stream
```
Returns `text/event-stream`. Events arrive in order:
1. `research_start` — DuckDuckGo searches beginning
2. `research_done` — with `citation_count`
3. `analysis_start` — LLM generation beginning
4. `done` — with `analysis_id`, or `error` with `message`
5. Periodic `ping` every 30 s if idle

If opened against a completed analysis, returns a single `done` or `error` event immediately.

---

## 4. Known Edge Cases & Failure Modes

### 4.1 "Be decisive" leakage

The classifier prompt instructs the LLM to only use `general` if the question is _equally_ ambiguous. In practice, questions like _"Tell me about the market and our competition"_ may be classified as `market_research` (returning 202) rather than `general` (returning 422 with a clarifying question). This is not a crash but produces an analysis the user didn't clearly ask for.

**Reproduce:** POST `/consult` with `"Tell me about the market and our competition"`. Expected: 422 + `general`. Observed risk: 202 + `market_research`.

### 4.2 Context truncation is silent

In `/analyses:generate`, the `context` field is truncated to 200 characters (raw question) and 150 characters (industry-prefixed query) when building DuckDuckGo search queries. There is no warning in the 202 response. A user passing detailed context may receive an analysis that didn't use all the context they provided.

### 4.3 DuckDuckGo rate limiting under concurrent load

When 5+ analyses are triggered concurrently, DuckDuckGo may throttle or block queries. This causes `gather_research` to return fewer than 4 citations (the `MIN_CITATIONS` threshold), causing the analysis to fail with `status: "failed"` and error `"Insufficient sources found (N)"`. There is no backoff, circuit-breaker, or retry logic.

### 4.4 SSE stream for non-existent analysis_id

The stream endpoint (`/analyses/{id}/stream`) does not have an `event_bus.exists()` guard. Streaming against a non-existent analysis_id may return 200 and hang rather than returning 404. Confirmed by test harness scenario P1-4.

### 4.5 /analyses:generate bypasses classification

Passing `analysis_type: "pestel"` with context about hiring decisions is accepted without validation — the type and content are never cross-checked. The resulting PESTEL analysis will apply a macro-environment lens to an HR question. This produces output that is structurally valid but semantically irrelevant.

### 4.6 Empty / whitespace-only questions

A question of `"   "` or `""` is not rejected by Pydantic (no `min_length` constraint). The classifier may accept it and classify it as `out_of_scope` or `general`, but it may also classify it as a valid type and produce a nonsensical analysis.

### 4.7 Non-English questions

Arabic questions (e.g. _"ما هي التهديدات التنافسية الأساسية التي تواجه شركتنا؟"_) do not crash the classifier and may be classified correctly (the classifier is prompted in English but the LLM handles multilingual input). However, the analysis output will be in English since all system prompts are English-only, which may surprise Arabic-speaking users.

### 4.8 Very thin brand profiles

If the brand profile has no `industry` set, the search queries fall back to `"general business"`, producing generic rather than brand-specific results. The analysis will still complete but will have low strategic specificity.

### 4.9 Eval agent non-determinism

`_judge_evidence_grounding` uses `random.sample` to select which claim-citation pairs to check. Two eval runs on the same analysis may produce different `evidence_grounding` scores. The criterion score in `results.eval` reflects the sample from the first run only.

---

## 5. Existing Eval Rubric

The following rubric is implemented in `app/agents/eval_agent.py` and `app/agents/eval_schemas.py`. **New scenarios should be assessed against these same criteria.** Verbatim pass thresholds:

### Five criteria

| Criterion | Type | Pass threshold | Hard gate? |
|---|---|---|---|
| `citation_support_rate` | Structural | ≥ 80% of items have verified citation indices | **Yes** — failure forces `EvalOutput.passed = False` regardless of other scores |
| `section_completeness` | Structural | All required sections present; SWOT sections ≥ 2 items each; feasibility `recommendation` must be one of `proceed \| proceed_with_caution \| do_not_proceed` | No |
| `evidence_grounding` | LLM judge | ≥ 66% of sampled claim-citation pairs are supported by the cited snippet | No |
| `recommendation_consistency` | LLM judge (feasibility only) | Score 0–3 ≥ 2 (normalised ≥ 0.50) | No |
| `internal_consistency` | LLM judge (swot/pestel only) | Consistency score 0–3 ≥ 2 (normalised ≥ 0.66) | No |

For `brand_analysis` and `market_research`: `recommendation_consistency` and `internal_consistency` are both N/A (score = 1.0, passed = true).

### Overall pass

```
overall_score = mean(all 5 criterion scores)
passed = (overall_score >= 0.75) AND citation_support_rate.passed
```

### Flags

Any criterion with `score < 0.5` (that isn't marked N/A) generates a human-readable flag string in `EvalOutput.flags`. Examples:
- `"Only 60% of claims have verified citations (need ≥80%)"`
- `"Incomplete sections: 'threats' has fewer than 2 items"`
- `"Low citation grounding: 3/5 sampled claims are grounded in cited sources"`

### `unverified` flag on items

When the LLM returns a `citation_indices` list that contains out-of-range integers, those indices are stripped and the item is marked `"unverified": true`. Unverified items count against `citation_support_rate`.

---

## 6. Example Request / Response Pairs

The following cases come from `scripts/sanity_check_intent.py` and `scripts/test_live_scenarios.py`. They represent the actual inputs used during development and the expected or observed outputs.

---

### Example 1 — Clear SWOT intent (happy path)

**Request:**
```
POST /api/workspaces/{ws_id}/consult
{ "question": "What are my brand's biggest weaknesses vs competitors?" }
```

**Expected 202:**
```json
{ "classified_as": "swot", "status": "generating" }
```

**Expected final `output` shape (swot):** all four sections present, each with ≥2 items, every item with citation indices pointing to real sources, `unverified: false` on all items.

---

### Example 2 — Feasibility with actionable recommendation

**Request:**
```
POST /api/workspaces/{ws_id}/consult
{ "question": "Should we launch a premium product line in Riyadh?" }
```

**Expected 202:**
```json
{ "classified_as": "feasibility", "status": "generating" }
```

**Expected final `output.recommendation`:** one of `"proceed"`, `"proceed_with_caution"`, or `"do_not_proceed"` — logically consistent with findings in `key_risks` and `market_size_and_growth`. `recommendation_rationale` must not be empty.

---

### Example 3 — Out-of-scope content creation request (hard decline)

**Request:**
```
POST /api/workspaces/{ws_id}/consult
{ "question": "Can you write me a LinkedIn post?" }
```

**Expected 422:**
```json
{
  "detail": {
    "classification": "out_of_scope",
    "message": "This platform handles strategic analysis. Try asking about market research or a SWOT."
  }
}
```

No analysis is created. No `id` is returned.

---

### Example 4 — Ambiguous question → clarifying question (general)

**Request:**
```
POST /api/workspaces/{ws_id}/consult
{ "question": "Tell me everything about my business" }
```

**Expected 422:**
```json
{
  "detail": {
    "classification": "general",
    "message": "Are you looking for a competitive SWOT, or more of a market landscape overview?"
  }
}
```

**Known risk:** due to the "be decisive" classifier instruction, this may instead return 202 classified as `market_research`. Both outcomes are currently accepted by the test harness (documented as P0-4).

---

### Example 5 — Arabic question (non-English robustness)

**Request:**
```
POST /api/workspaces/{ws_id}/consult
{ "question": "ما هي التهديدات التنافسية الأساسية التي تواجه شركتنا؟" }
```

**Observed:** `status 202` or `status 422` — no 500. Classification is typically `swot` (the question maps to threats). The resulting analysis output will be in English despite the Arabic question.

---

## 7. Constraints & Non-Goals

The following are explicit constraints baked into the system design. Eval scenarios should not penalise the bot for these; instead, any scenario that bumps into them should verify the documented behaviour occurs cleanly.

| Constraint | Detail |
|---|---|
| No multi-turn context | Each `/consult` call is stateless. There is no session, conversation history, or memory of prior analyses. |
| No token streaming | The endpoint uses an async job pattern (202 + poll/SSE), not per-token streaming. `with_structured_output` disables token streaming on the analysis LLM. |
| Citations from DuckDuckGo only | Research is limited to live DuckDuckGo text search. No proprietary databases, paywalled content, or internal documents. |
| English-only output | All system prompts are in English. The analysis output is always in English regardless of question language. |
| Arabic disclaimer always appended | `results.disclaimer` is a fixed Arabic string appended to every completed analysis. It is not localised and is always present. |
| Context truncated at 200 chars | The raw `context` / `question` is truncated to 200 characters when appended to search queries; the industry-prefixed variant is truncated to 150 characters. No warning is emitted. |
| Minimum 4 citations required | If DuckDuckGo returns fewer than 4 unique results, the analysis fails (`status: "failed"`) without calling the generation LLM. |
| No citation fact-checking against URLs | The system only uses the short `snippet` returned by DuckDuckGo, not the full page content. Evidence grounding is limited to that 300-character snippet. |
| `/analyses:generate` bypasses classification | This endpoint does not run intent classification. It accepts any of the five `analysis_type` values without verifying that the `context` is semantically appropriate. |
| Eval is non-deterministic | `evidence_grounding` samples randomly; two eval runs on the same completed analysis may yield different scores. |
