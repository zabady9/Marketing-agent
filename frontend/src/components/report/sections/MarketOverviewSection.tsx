import type { MarketOverviewData } from '../../../types'
import { formatCurrency } from '../../../lib/format'
import { buildCitationRegistry } from '../citations'
import { SourceBadge } from '../SourceBadge'
import { ClassificationBadge } from '../ClassificationBadge'
import { MethodologyDisclosure } from '../MethodologyDisclosure'
import { JargonTerm } from '../JargonTerm'
import { ANCHOR_PREFIX } from '../anchors'
import { TamSamSomChart } from '../charts/TamSamSomChart'

export function marketOverviewRegistry(data: MarketOverviewData) {
  return buildCitationRegistry([
    data.citations,
    data.growth_rate_citations,
    data.tam.citations,
    data.sam.citations,
    data.som.citations,
  ])
}

function FigureRow({
  label,
  figure,
  registry,
}: {
  label: string
  figure: MarketOverviewData['tam']
  registry: ReturnType<typeof marketOverviewRegistry>
}) {
  return (
    <div className="rounded-lg border border-gray-200 p-3">
      <div className="flex items-center gap-1.5">
        <p className="text-xs font-medium text-gray-500">
          <JargonTerm term={label}>{label}</JargonTerm>
        </p>
        <ClassificationBadge claimType={figure.claim_type} />
        <SourceBadge citations={figure.citations} registry={registry} anchorPrefix={ANCHOR_PREFIX.market} />
      </div>
      <p className="mt-0.5 text-lg font-semibold text-gray-900">
        {figure.value === null ? 'Unavailable' : formatCurrency(figure.value, figure.currency)}
      </p>
      <p className="text-[11px] text-gray-400">confidence: {figure.confidence}</p>
      <MethodologyDisclosure methodology={figure.methodology} />
    </div>
  )
}

export function MarketOverviewSection({ data }: { data: MarketOverviewData }) {
  const registry = marketOverviewRegistry(data)

  return (
    <section id="market-overview" className="scroll-mt-20">
      <h2 className="text-xl font-semibold text-gray-900 mb-3">Market Overview</h2>

      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <TamSamSomChart
          tam={data.tam}
          sam={data.sam}
          som={data.som}
          growthRateCagr={data.growth_rate_cagr}
        />
        <div className="mt-2 flex items-center gap-1.5 text-xs text-gray-500">
          <span>Growth rate classification:</span>
          <ClassificationBadge claimType={data.growth_rate_claim_type} />
          <SourceBadge
            citations={data.growth_rate_citations}
            registry={registry}
            anchorPrefix={ANCHOR_PREFIX.market}
          />
        </div>
        <MethodologyDisclosure methodology={data.growth_rate_methodology} />

        <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-3">
          <FigureRow label="TAM" figure={data.tam} registry={registry} />
          <FigureRow label="SAM" figure={data.sam} registry={registry} />
          <FigureRow label="SOM" figure={data.som} registry={registry} />
        </div>

        {data.narrative?.text && (
          <div className="mt-4">
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-medium text-gray-500">Narrative</p>
              <ClassificationBadge claimType={data.claim_types?.narrative} />
            </div>
            <p className="mt-1 text-sm text-gray-700">{data.narrative.text}</p>
          </div>
        )}

        {data.key_insights.length > 0 && (
          <div className="mt-4">
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-medium text-gray-500">Key insights</p>
              <ClassificationBadge claimType={data.claim_types?.key_insights} />
            </div>
            <ul className="mt-1 list-disc list-inside text-sm text-gray-700 space-y-0.5">
              {data.key_insights.map((insight, i) => (
                <li key={i}>{insight}</li>
              ))}
            </ul>
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
