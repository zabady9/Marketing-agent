import type { ExecutiveSummaryData } from '../../../types'
import { ClassificationBadge } from '../ClassificationBadge'
import { ConfidenceMeter } from '../charts/ConfidenceMeter'

const VERDICT_CLASSES: Record<ExecutiveSummaryData['verdict'], string> = {
  proceed: 'bg-emerald-100 text-emerald-700',
  proceed_with_caution: 'bg-amber-100 text-amber-700',
  do_not_proceed: 'bg-red-100 text-red-700',
}

function VerdictBadge({ verdict }: { verdict: ExecutiveSummaryData['verdict'] }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ${VERDICT_CLASSES[verdict]}`}
    >
      {verdict.replace(/_/g, ' ')}
    </span>
  )
}

function StringList({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="text-sm text-gray-400">None reported.</p>
  return (
    <ul className="list-disc list-inside text-sm text-gray-700 space-y-0.5">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  )
}

export function ExecutiveSummarySection({ data }: { data: ExecutiveSummaryData }) {
  return (
    <section id="executive-summary" className="scroll-mt-20">
      <h2 className="text-xl font-semibold text-gray-900 mb-3">Executive Summary</h2>

      <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-5">
        <div className="flex flex-wrap items-center gap-2">
          <VerdictBadge verdict={data.verdict} />
          <ClassificationBadge claimType={data.claim_types?.verdict} />
        </div>

        <div>
          <div className="flex items-center gap-1.5 mb-1">
            <ClassificationBadge claimType={data.claim_types?.confidence_score} />
          </div>
          <ConfidenceMeter confidenceScore={data.confidence_score} breakdown={data.confidence_breakdown} />
        </div>

        {data.executive_summary?.text && (
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-medium text-gray-500">Summary</p>
              <ClassificationBadge claimType={data.claim_types?.executive_summary} />
            </div>
            <p className="mt-1 text-sm text-gray-700">{data.executive_summary.text}</p>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-medium text-gray-500">Key opportunities</p>
              <ClassificationBadge claimType={data.claim_types?.key_opportunities} />
            </div>
            <div className="mt-1">
              <StringList items={data.key_opportunities} />
            </div>
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-medium text-gray-500">Key risks</p>
              <ClassificationBadge claimType={data.claim_types?.key_risks} />
            </div>
            <div className="mt-1">
              <StringList items={data.key_risks} />
            </div>
          </div>
        </div>

        <div>
          <div className="flex items-center gap-1.5">
            <p className="text-xs font-medium text-gray-500">Data gaps</p>
            <ClassificationBadge claimType={data.claim_types?.data_gaps} />
          </div>
          <div className="mt-1">
            <StringList items={data.data_gaps} />
          </div>
        </div>

        <div>
          <div className="flex items-center gap-1.5">
            <p className="text-xs font-medium text-gray-500">Contradictions</p>
            <ClassificationBadge claimType={data.claim_types?.contradictions} />
          </div>
          <div className="mt-1">
            <StringList items={data.contradictions} />
          </div>
        </div>

        {data.rationale?.text && (
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-medium text-gray-500">Rationale</p>
              <ClassificationBadge claimType={data.claim_types?.rationale} />
            </div>
            <p className="mt-1 text-sm text-gray-700">{data.rationale.text}</p>
          </div>
        )}
      </div>
    </section>
  )
}
