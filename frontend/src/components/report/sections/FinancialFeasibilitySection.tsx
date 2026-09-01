import type { CalculatedFigure, FinancialFeasibilityData, NPVFigure } from '../../../types'
import { formatCurrency, formatNumber, formatPercent } from '../../../lib/format'
import { ClassificationBadge } from '../ClassificationBadge'
import { MethodologyDisclosure } from '../MethodologyDisclosure'
import { JargonTerm } from '../JargonTerm'
import { SensitivityCharts } from '../charts/SensitivityCharts'
import { CashFlowChart } from '../charts/CashFlowChart'
import { CostStructureChart } from '../charts/CostStructureChart'

function CalcFigureCard({
  label,
  term,
  figure,
  format,
}: {
  label: string
  term: string
  figure: CalculatedFigure
  format: (v: number) => string
}) {
  return (
    <div className="rounded-lg border border-gray-200 p-3">
      <div className="flex items-center gap-1.5">
        <p className="text-xs font-medium text-gray-500">
          <JargonTerm term={term}>{label}</JargonTerm>
        </p>
        <ClassificationBadge claimType={figure.claim_type} />
      </div>
      <p className="mt-0.5 text-lg font-semibold text-gray-900">
        {figure.value === null ? '—' : format(figure.value)}
      </p>
      {figure.input_confidence === 'low' && (
        <p className="text-[11px] text-amber-600">low-confidence inputs</p>
      )}
      <MethodologyDisclosure
        methodology={figure.calculation_trace?.methodology}
        inputs={figure.calculation_trace?.inputs}
        output={figure.calculation_trace?.output}
      />
    </div>
  )
}

function roiYearKeys(data: FinancialFeasibilityData): { label: string; figure: CalculatedFigure }[] {
  return Object.keys(data)
    .filter((k) => /^roi_year_\d+$/.test(k))
    .sort((a, b) => Number(a.split('_').pop()) - Number(b.split('_').pop()))
    .map((k) => ({
      label: `ROI (year ${k.split('_').pop()})`,
      figure: data[k] as CalculatedFigure,
    }))
}

export function FinancialFeasibilitySection({ data }: { data: FinancialFeasibilityData }) {
  const npv = data.npv as NPVFigure
  const currency = data.capex.currency || data.opex_monthly.currency || 'USD'

  return (
    <section id="financial-feasibility" className="scroll-mt-20">
      <h2 className="text-xl font-semibold text-gray-900 mb-3">Financial Feasibility</h2>

      <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-5">
        <div>
          <p className="mb-2 text-xs font-medium text-gray-500">Inputs</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="rounded-lg border border-gray-200 p-3">
              <div className="flex items-center gap-1.5">
                <p className="text-xs font-medium text-gray-500">
                  <JargonTerm term="Capex">Capex</JargonTerm>
                </p>
                <ClassificationBadge claimType={data.capex.claim_type} />
              </div>
              <p className="mt-0.5 text-lg font-semibold text-gray-900">
                {formatCurrency(data.capex.value, data.capex.currency)}
              </p>
              <p className="text-[11px] text-gray-400">{data.capex.source.replace('_', ' ')}</p>
            </div>
            <div className="rounded-lg border border-gray-200 p-3">
              <div className="flex items-center gap-1.5">
                <p className="text-xs font-medium text-gray-500">
                  Monthly <JargonTerm term="Opex">Opex</JargonTerm>
                </p>
                <ClassificationBadge claimType={data.opex_monthly.claim_type} />
              </div>
              <p className="mt-0.5 text-lg font-semibold text-gray-900">
                {formatCurrency(data.opex_monthly.value, data.opex_monthly.currency)}
              </p>
              <p className="text-[11px] text-gray-400">{data.opex_monthly.source.replace('_', ' ')}</p>
            </div>
          </div>
        </div>

        <div>
          <p className="mb-2 text-xs font-medium text-gray-500">Calculated figures</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <CalcFigureCard
              label="Break-even (months)"
              term="Break-even"
              figure={data.break_even_months}
              format={(v) => formatNumber(v, 1)}
            />
            <CalcFigureCard
              label="Break-even (units)"
              term="Break-even"
              figure={data.break_even_units}
              format={(v) => formatNumber(v, 0)}
            />
            {roiYearKeys(data).map(({ label, figure }) => (
              <CalcFigureCard key={label} label={label} term="ROI" figure={figure} format={(v) => formatPercent(v)} />
            ))}
            <CalcFigureCard
              label={`NPV${npv.is_positive ? ' (positive)' : ' (negative)'}`}
              term="NPV"
              figure={npv}
              format={(v) => formatCurrency(v, currency)}
            />
          </div>
        </div>

        <div>
          <div className="mb-2 flex items-center gap-1.5">
            <p className="text-xs font-medium text-gray-500">Sensitivity analysis</p>
            <ClassificationBadge claimType={data.sensitivity_analysis.claim_type} />
          </div>
          <SensitivityCharts scenarios={data.sensitivity_analysis.value} currency={currency} />
          <MethodologyDisclosure
            methodology={data.sensitivity_analysis.calculation_trace?.methodology}
            inputs={data.sensitivity_analysis.calculation_trace?.inputs}
            output={data.sensitivity_analysis.calculation_trace?.output}
          />
        </div>

        <div>
          <div className="mb-2 flex items-center gap-1.5">
            <p className="text-xs font-medium text-gray-500">Cash flow projection</p>
            <ClassificationBadge claimType={data.cash_flow.claim_type} />
          </div>
          <CashFlowChart cashFlow={data.cash_flow} currency={currency} />
          <MethodologyDisclosure
            methodology={data.cash_flow.calculation_trace?.methodology}
            inputs={data.cash_flow.calculation_trace?.inputs}
            output={data.cash_flow.calculation_trace?.output}
          />
        </div>

        <div>
          <div className="mb-2 flex items-center gap-1.5">
            <p className="text-xs font-medium text-gray-500">Cost structure</p>
            <ClassificationBadge claimType={data.cost_structure.claim_type} />
          </div>
          <CostStructureChart value={data.cost_structure.value} currency={currency} />
          <MethodologyDisclosure
            methodology={data.cost_structure.calculation_trace?.methodology}
            inputs={data.cost_structure.calculation_trace?.inputs}
            output={data.cost_structure.calculation_trace?.output}
          />
        </div>

        {data.narrative?.text && (
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-medium text-gray-500">Narrative</p>
              <ClassificationBadge claimType={data.claim_types?.narrative} />
            </div>
            <p className="mt-1 text-sm text-gray-700">{data.narrative.text}</p>
          </div>
        )}

        <p className="text-[11px] text-gray-400">
          Financial figures are deterministic calculations, not sourced from citations — see each
          figure's Methodology disclosure for its calculation trace.
        </p>
      </div>
    </section>
  )
}
