import type { CompetitiveLandscapeData, CompetitorProfile } from '../../../types'
import { buildCitationRegistry } from '../citations'
import { SourceBadge } from '../SourceBadge'
import { ClassificationBadge } from '../ClassificationBadge'
import { MethodologyDisclosure } from '../MethodologyDisclosure'
import { DataTable } from '../DataTable'
import { CompetitorPositionChart } from '../charts/CompetitorPositionChart'
import { ANCHOR_PREFIX } from '../anchors'

export function competitiveLandscapeRegistry(data: CompetitiveLandscapeData) {
  return buildCitationRegistry([data.citations, ...data.competitors.map((c) => c.citations)])
}

const POSITION_CLASSES: Record<CompetitorProfile['market_position'], string> = {
  leader: 'bg-indigo-100 text-indigo-700',
  challenger: 'bg-blue-100 text-blue-700',
  niche: 'bg-teal-100 text-teal-700',
  unknown: 'bg-gray-100 text-gray-600',
}

function StringList({ items }: { items: string[] }) {
  if (items.length === 0) return <span className="text-gray-400">—</span>
  return (
    <ul className="list-disc list-inside space-y-0.5">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  )
}

export function CompetitiveLandscapeSection({ data }: { data: CompetitiveLandscapeData }) {
  const registry = competitiveLandscapeRegistry(data)

  return (
    <section id="competitive-landscape" className="scroll-mt-20">
      <h2 className="text-xl font-semibold text-gray-900 mb-3">Competitive Landscape</h2>

      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <p className="mb-2 text-xs font-medium text-gray-500">Competitors by market position</p>
        <CompetitorPositionChart competitors={data.competitors} />

        <p className="mt-4 mb-2 text-xs font-medium text-gray-500">All competitors</p>
        <DataTable<CompetitorProfile>
          rows={data.competitors}
          rowKey={(c, i) => `${c.name}-${i}`}
          columns={[
            {
              header: 'Competitor',
              render: (c) => (
                <div>
                  <p className="font-medium text-gray-900">{c.name}</p>
                  <p className="text-[11px] text-gray-400">{c.source.replace('_', ' ')}</p>
                </div>
              ),
            },
            {
              header: 'Position',
              render: (c) => (
                <span
                  className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium capitalize whitespace-nowrap ${POSITION_CLASSES[c.market_position]}`}
                >
                  {c.market_position}
                </span>
              ),
            },
            { header: 'Strengths', render: (c) => <StringList items={c.strengths} /> },
            { header: 'Weaknesses', render: (c) => <StringList items={c.weaknesses} /> },
            {
              header: 'Classification',
              render: (c) => (
                <div className="flex items-center gap-1">
                  <ClassificationBadge claimType={c.claim_type} />
                  <SourceBadge
                    citations={c.citations}
                    registry={registry}
                    anchorPrefix={ANCHOR_PREFIX.competitive}
                  />
                </div>
              ),
            },
          ]}
        />
        {data.competitors.some((c) => c.methodology) && (
          <div className="mt-2 space-y-1">
            {data.competitors
              .filter((c) => c.methodology)
              .map((c) => (
                <MethodologyDisclosure key={c.name} methodology={`${c.name}: ${c.methodology}`} />
              ))}
          </div>
        )}

        {data.narrative?.text && (
          <div className="mt-4">
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-medium text-gray-500">Narrative</p>
              <ClassificationBadge claimType={data.claim_types?.narrative} />
            </div>
            <p className="mt-1 text-sm text-gray-700">{data.narrative.text}</p>
          </div>
        )}

        <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-medium text-gray-500">Key differentiators</p>
              <ClassificationBadge claimType={data.claim_types?.key_differentiators} />
            </div>
            <div className="mt-1 text-sm text-gray-700">
              <StringList items={data.key_differentiators} />
            </div>
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-medium text-gray-500">Market gaps</p>
              <ClassificationBadge claimType={data.claim_types?.market_gaps} />
            </div>
            <div className="mt-1 text-sm text-gray-700">
              <StringList items={data.market_gaps} />
            </div>
          </div>
        </div>

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
