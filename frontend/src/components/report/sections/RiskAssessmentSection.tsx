import { useState } from 'react'
import type { RiskAssessmentData, RiskEntry } from '../../../types'
import { buildCitationRegistry } from '../citations'
import { SourceBadge } from '../SourceBadge'
import { ClassificationBadge } from '../ClassificationBadge'
import { MethodologyDisclosure } from '../MethodologyDisclosure'
import { DataTable } from '../DataTable'
import { RiskMatrix } from '../RiskMatrix'
import { RiskCategoryChart } from '../charts/RiskCategoryChart'
import { ANCHOR_PREFIX } from '../anchors'

export function riskAssessmentRegistry(data: RiskAssessmentData) {
  return buildCitationRegistry([data.citations, ...data.risks.map((r) => r.citations)])
}

const LEVEL_CLASSES: Record<RiskEntry['probability'], string> = {
  high: 'bg-red-100 text-red-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-emerald-100 text-emerald-700',
}

function LevelBadge({ level }: { level: RiskEntry['probability'] }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ${LEVEL_CLASSES[level]}`}
    >
      {level}
    </span>
  )
}

export function RiskAssessmentSection({ data }: { data: RiskAssessmentData }) {
  const registry = riskAssessmentRegistry(data)
  const [highlighted, setHighlighted] = useState<number | null>(null)

  function selectRisk(index: number) {
    setHighlighted(index)
    document.getElementById(`risk-row-${index}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  return (
    <section id="risk-assessment" className="scroll-mt-20">
      <h2 className="text-xl font-semibold text-gray-900 mb-3">Risk Assessment</h2>

      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <p className="text-sm text-gray-700 mb-3">
          <span className="font-semibold">{data.high_critical_count}</span> high-probability /
          high-impact risk{data.high_critical_count === 1 ? '' : 's'} identified out of{' '}
          {data.risks.length} total.
        </p>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div>
            <p className="mb-2 text-xs font-medium text-gray-500">Probability × impact matrix</p>
            <RiskMatrix risks={data.risks} onSelectRisk={selectRisk} />
          </div>
          <div>
            <p className="mb-2 text-xs font-medium text-gray-500">Risks by category</p>
            <RiskCategoryChart risks={data.risks} />
          </div>
        </div>

        <p className="mt-5 mb-2 text-xs font-medium text-gray-500">All risks</p>
        <DataTable<RiskEntry>
          rows={data.risks}
          rowKey={(_r, i) => `risk-${i}`}
          rowId={(_r, i) => `risk-row-${i}`}
          rowClassName={(_r, i) => (i === highlighted ? 'bg-indigo-50 ring-1 ring-inset ring-indigo-300' : '')}
          columns={[
            {
              header: 'Risk',
              render: (r) => (
                <div>
                  <div className="flex items-start gap-1">
                    <span>{r.risk_description}</span>
                    <SourceBadge citations={r.citations} registry={registry} anchorPrefix={ANCHOR_PREFIX.risk} />
                  </div>
                  <MethodologyDisclosure methodology={r.methodology} />
                </div>
              ),
            },
            { header: 'Category', render: (r) => <span className="capitalize">{r.category}</span> },
            { header: 'Probability', render: (r) => <LevelBadge level={r.probability} /> },
            { header: 'Impact', render: (r) => <LevelBadge level={r.impact} /> },
            { header: 'Mitigation', render: (r) => r.mitigation },
            {
              header: 'Classification',
              render: (r) => <ClassificationBadge claimType={r.claim_type} />,
            },
          ]}
        />

        {data.narrative?.text && (
          <div className="mt-4">
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-medium text-gray-500">Narrative</p>
              <ClassificationBadge claimType={data.claim_types?.narrative} />
            </div>
            <p className="mt-1 text-sm text-gray-700">{data.narrative.text}</p>
          </div>
        )}

        {data.search_queries_used.length > 0 && (
          <p className="mt-3 text-[11px] text-gray-400">
            Research queries: {data.search_queries_used.join(' · ')}
          </p>
        )}
        <p className="mt-3 text-[11px] text-gray-400">
          Sources for this section are numbered above and listed in the Methodology &amp; Sources
          appendix.
        </p>
      </div>
    </section>
  )
}
