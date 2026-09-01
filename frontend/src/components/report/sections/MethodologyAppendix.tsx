import type { CompetitiveLandscapeData, MarketOverviewData, RiskAssessmentData } from '../../../types'
import { CitationFootnotes } from '../CitationFootnotes'
import { ClassificationLegend } from '../ClassificationBadge'
import { ANCHOR_PREFIX } from '../anchors'
import { marketOverviewRegistry } from './MarketOverviewSection'
import { competitiveLandscapeRegistry } from './CompetitiveLandscapeSection'
import { riskAssessmentRegistry } from './RiskAssessmentSection'

// Closing appendix — consolidates every section's citation footnotes (each
// keeping that section's own 1..N numbering, matching the SourceBadge links
// scattered through the report above) plus a plain-language note on how the
// pipeline works and the classification legend, shown once here rather than
// repeated per section.
export function MethodologyAppendix({
  market,
  competitive,
  risk,
  glossary,
}: {
  market?: MarketOverviewData
  competitive?: CompetitiveLandscapeData
  risk?: RiskAssessmentData
  glossary?: Record<string, string>
}) {
  const hasAnyCitations =
    (market && marketOverviewRegistry(market).citations.length > 0) ||
    (competitive && competitiveLandscapeRegistry(competitive).citations.length > 0) ||
    (risk && riskAssessmentRegistry(risk).citations.length > 0)

  return (
    <section id="methodology-sources" className="scroll-mt-20">
      <h2 className="text-xl font-semibold text-gray-900 mb-3">Methodology &amp; Sources</h2>

      <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-6">
        <div className="text-sm text-gray-700 space-y-2">
          <p>
            This report combines two kinds of claims. <strong>Financial figures</strong> (break-even,
            ROI, NPV, sensitivity, cash flow) come from a deterministic calculation tool — the same
            inputs always produce the same outputs, and each figure carries a calculation trace you
            can expand via its "Methodology" disclosure. <strong>Market, competitor, and risk
            claims</strong> come from an AI research agent that searches the web and grounds each
            claim in a numbered citation index; claims it could not source are explicitly marked
            unavailable rather than guessed.
          </p>
          <p>
            Every classification pill in this report (see legend below) reflects how a claim was
            produced, not how confident the AI "feels" about it — that judgment is separate, and
            shown in the Executive Summary's confidence score.
          </p>
          <p>
            Before a claim is labeled "Verified", an auxiliary model check reviews whether its
            citation actually supports that specific claim — not just whether it's topically
            related — and downgrades it to "Opinion" when it doesn't (e.g. a citation about a
            same-named business in a different city or industry). This check meaningfully reduces
            mismatched citations but, like any model-based check, may not catch every case — treat
            "Verified" as well-supported, not infallible.
          </p>
        </div>

        <div>
          <p className="mb-2 text-xs font-semibold text-gray-500">Classification legend</p>
          <ClassificationLegend />
        </div>

        {glossary && Object.keys(glossary).length > 0 && (
          <div>
            <p className="mb-2 text-xs font-semibold text-gray-500">Glossary</p>
            <p className="mb-2 text-[11px] text-gray-400">
              These terms stay in English throughout the report (standard practice even in
              translated business documents) — definitions below are in the report's language.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-1.5 text-xs">
              {Object.entries(glossary).map(([term, definition]) => (
                <p key={term} className="text-gray-600">
                  <span className="font-semibold text-gray-800">{term}</span> — {definition}
                </p>
              ))}
            </div>
          </div>
        )}

        {hasAnyCitations && (
          <div>
            <p className="mb-2 text-xs font-semibold text-gray-500">Sources by section</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8">
              {market && (
                <div>
                  <p className="text-xs font-medium text-gray-600 mb-1">Market Overview</p>
                  <CitationFootnotes registry={marketOverviewRegistry(market)} anchorPrefix={ANCHOR_PREFIX.market} />
                </div>
              )}
              {competitive && (
                <div>
                  <p className="text-xs font-medium text-gray-600 mb-1">Competitive Landscape</p>
                  <CitationFootnotes
                    registry={competitiveLandscapeRegistry(competitive)}
                    anchorPrefix={ANCHOR_PREFIX.competitive}
                  />
                </div>
              )}
              {risk && (
                <div>
                  <p className="text-xs font-medium text-gray-600 mb-1">Risk Assessment</p>
                  <CitationFootnotes registry={riskAssessmentRegistry(risk)} anchorPrefix={ANCHOR_PREFIX.risk} />
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
