# Consulting Endpoint — Test Scenarios

Generated from `bot-eval-context.md`. Organized by what each scenario is actually probing: routing correctness, output structure, rubric compliance, and documented edge cases. Each scenario states the input, the expected behavior per the spec, and what to check when grading the actual response.

Legend for **Checks against rubric**: CSR = citation_support_rate, SC = section_completeness, EG = evidence_grounding, RC = recommendation_consistency, IC = internal_consistency.

---

## A. Happy-path routing + output quality (one per analysis type)

### A1 — SWOT, clear intent
**Input:** `POST /consult {"question": "What are my brand's biggest weaknesses vs competitors?"}`
**Expected:** 202, `classified_as: "swot"`.
**On completion, check:**
- All four sections present, each ≥2 items (SC)
- Every item has valid `citation_indices` into the source list, `unverified: false` (CSR)
- Sampled claims are actually supported by their cited snippet, not just formatted correctly (EG)
- Strengths/weaknesses don't contradict opportunities/threats in an obviously incoherent way (IC)

### A2 — PESTEL, clear intent
**Input:** `"How will new e-invoicing regulations affect our operations?"`
**Expected:** 202, `classified_as: "pestel"`.
**Check:** all six sections present (political/economical/social/technological/environmental/legal), legal section actually addresses the regulation named in the question rather than generic filler (SC, IC).

### A3 — Feasibility, decision-oriented question
**Input:** `"Should we launch a premium product line in Riyadh?"`
**Expected:** 202, `classified_as: "feasibility"`.
**Check:** `recommendation` is one of the three enum values; `recommendation_rationale` is non-empty and actually references `key_risks` / `market_size_and_growth` content rather than being generic boilerplate (RC — this is the main thing worth grading by hand here, since a model can satisfy the enum constraint while writing a rationale that doesn't logically follow from its own findings).

### A4 — Brand analysis, positioning-focused
**Input:** `"Is our messaging consistent with how our target audience sees us?"`
**Expected:** 202, `classified_as: "brand_analysis"`.
**Check:** all three sections present, `summary_recommendation` non-empty, gap_or_strength fields are specific rather than restating current_state (SC).

### A5 — Market research, landscape question
**Input:** `"What does the competitive landscape look like for our industry right now?"`
**Expected:** 202, `classified_as: "market_research"`.
**Check:** segments have plausible `size_estimate`/`growth_trend` grounded in citations, `key_players` aren't hallucinated names absent from any source snippet (CSR, EG).

---

## B. Classification boundary cases

These target §4.1 directly — the "be decisive" leakage risk is the single highest-value thing to test repeatedly, since it's a documented known gap rather than a hypothetical.

### B1 — Genuinely dual-mapping question
**Input:** `"Tell me about the market and our competition."`
**Expected per spec:** 422, `classification: "general"`, clarifying message.
**Actually test for:** whether it instead returns 202 as `market_research` (the documented risk). Run this **5-10 times** — since the classifier is an LLM call, the leakage may be probabilistic rather than deterministic. Record the split. This is more useful as a frequency measurement than a pass/fail.

### B2 — Maximally vague question
**Input:** `"Tell me everything about my business"`
**Expected:** 422, `general`, with a clarifying question that offers ≥2 concrete analysis-type options (per Example 4 in the spec).
**Check:** does the clarifying message actually name specific analysis types, or is it generic ("could you clarify?")? A vague clarifying question is a quality failure even if the classification itself is correct.

### B3 — Hard out-of-scope, unambiguous
**Input:** `"Can you write me a LinkedIn post?"`
**Expected:** 422, `out_of_scope`, polite decline, **no `id` in response**.
**Check:** decline message doesn't apologize excessively or hedge — should cleanly redirect to what the platform does (per Example 3).

### B4 — Soft out-of-scope (adjacent but not strategic)
**Input:** `"What's a good subject line for our next newsletter?"`
**Expected:** 422, `out_of_scope`.
**Why this matters more than B3:** B3 is obviously out of scope; this one is business-adjacent and plausibly tempting for a classifier to misroute into `brand_analysis`. Good test of whether "be decisive" bleeds into the wrong direction here too.

### B5 — HR/finance/ops question dressed as strategy
**Input:** `"Should we give our new hires a signing bonus?"`
**Expected:** 422, `out_of_scope` (per §1, HR questions are explicitly excluded).
**Check:** confirm it isn't misrouted into `feasibility` just because "should we" sounds decision-like.

### B6 — Question that names two analysis types explicitly
**Input:** `"Give me a SWOT and also tell me about the macro environment."`
**Expected:** ambiguous by construction — could reasonably go either way, or should be `general`. Useful to see which single type wins and whether the response acknowledges it only covered one framework.

---

## C. Input robustness / malformed input

### C1 — Empty string
**Input:** `{"question": ""}`
**Per §4.6:** not rejected by Pydantic. Check what the classifier actually does with it — `out_of_scope`, `general`, or (failure case) a fabricated analysis with no real basis.

### C2 — Whitespace-only
**Input:** `{"question": "   "}`
**Same check as C1** — verify consistent behavior between the two rather than one being handled and the other not.

### C3 — Extremely long question (context truncation, §4.2)
**Input:** a 600+ character question packed with specific detail in the back half (e.g., front-loaded generic framing, then very specific constraints after character ~250).
**Check:** does the resulting analysis reflect the detail that was truncated away? This is the actual bug surface — not whether truncation happens (it will, silently, by design) but whether the *user-visible output quality degrades* without any signal that it happened.

### C4 — Arabic question
**Input:** `"ما هي التهديدات التنافسية الأساسية التي تواجه شركتنا؟"`
**Expected per §4.7 / Example 5:** classification succeeds (typically `swot`), no 500. Output is in English regardless.
**Check:** classification accuracy on non-English input specifically — does it map to the same type an equivalent English question would, or does translation-via-classifier introduce drift?

### C5 — Mixed-language question (Arabic + English business terms)
**Input:** `"ما هو تحليل SWOT المناسب لعلامتنا التجارية في السوق السعودي؟"`
**Check:** same as C4, plus whether embedded English terms (SWOT) bias the classification toward that type regardless of actual intent.

### C6 — Thin brand profile (§4.8)
**Setup:** workspace with brand profile missing `industry`.
**Input:** any clear SWOT question.
**Expected:** falls back to `"general business"` search queries, completes successfully but with low specificity.
**Check:** does the output *read* as generic (interchangeable with any other brand), or does the model compensate with brand-name-specific claims it can't actually support? The failure mode to catch here is confident-sounding genericness, not an error.

---

## D. `/analyses:generate` — classification bypass (§4.5)

### D1 — Type/content mismatch, mild
**Input:** `POST /analyses:generate {"analysis_type": "pestel", "context": "We're deciding whether to give our new hires a signing bonus."}`
**Expected:** 202 accepted (Pydantic only validates the enum, not semantic fit). Analysis completes.
**Check:** does the resulting PESTEL output produce structurally valid but semantically empty content (generic macro-environment filler with no real connection to hiring), or does it — worse — fabricate a strained connection to make the mismatch look intentional? Per §4.5 this is expected to complete; the eval question is *how badly* it stretches to fill sections it has nothing legitimate to say about.

### D2 — Type/content mismatch, extreme
**Input:** `{"analysis_type": "market_research", "context": "What should I name my cat?"}`
**Check:** same as D1 but at the extreme end — useful for finding the actual floor of output quality when there's no real content to work with. Also confirms `context` truncation limits (200/150 chars) don't themselves prevent the mismatch.

---

## E. Rubric-targeted stress tests

These are designed to specifically pressure one criterion rather than test the system end-to-end.

### E1 — Citation floor (CSR hard gate)
**Setup:** a question about a very obscure or newly-founded brand/industry likely to return sparse DuckDuckGo results.
**Expected:** if <4 unique citations, `status: "failed"` with `"Insufficient sources found (N)"` per §4.3/constraints. If ≥4 but sparse, check whether `citation_support_rate` still clears 80% — sparse sources make it easier for the model to over-cite one source across unrelated claims.

### E2 — Concurrent load (§4.3)
**Setup:** fire 5+ `/consult` requests concurrently against different workspaces.
**Expected:** some may fail with insufficient-citations errors due to DuckDuckGo throttling, not due to actual research being thin. **Check:** is the failure rate under concurrency meaningfully higher than sequential runs of the same questions? This isolates infra-induced failures from genuine content gaps — worth flagging separately since it inflates apparent quality failures that aren't about the LLM at all.

### E3 — Feasibility internal consistency
**Input:** a feasibility question where the obvious research answer points toward risk (e.g., a saturated, heavily regulated market).
**Check:** does `recommendation` actually say `do_not_proceed` or `proceed_with_caution`, or does it default to an optimistic `proceed` regardless of its own `key_risks` content? This is the most concrete way to catch RC failures — pick questions where you can predict the "correct" recommendation direction in advance and see if the model's own stated risks agree with its final call.

### E4 — Eval non-determinism (§4.9)
**Setup:** take one completed analysis, run the eval agent against it 3 separate times.
**Check:** record the spread in `evidence_grounding` scores across runs. If the spread is wide enough to flip `passed` near the 0.75 threshold, that's worth knowing before trusting any single eval run as ground truth for a borderline case.

---

## F. Infra / API-contract edge cases (not response-quality, but worth including since they affect what "the bot" means)

### F1 — SSE stream against a non-existent `analysis_id`
**Expected per §4.4:** documented bug — likely hangs on 200 instead of returning 404.
**Check:** confirm current behavior, since this affects how any automated eval harness should be built (don't blindly poll/stream against IDs without existence-checking first).

### F2 — SSE stream opened after completion
**Input:** open the stream endpoint against an already-`ready` analysis.
**Expected:** single immediate `done` event.
**Check:** just confirming no hang, no duplicate events, no stale `research_start`/`analysis_start` replay.

---

## Suggested run order

1. **A1-A5** first — confirms baseline output quality per type before hunting edge cases.
2. **B1-B6** — routing is the highest-leverage place for silent failures since a misroute produces a *confident, well-formed wrong answer* rather than an obvious error.
3. **E1, E3, E4** — rubric stress tests, since these tell you whether the rubric itself is catching what it's supposed to catch.
4. **C1-C6, D1-D2, F1-F2** — lower priority; documented/expected edge cases, mostly confirming behavior matches spec rather than discovering anything new.