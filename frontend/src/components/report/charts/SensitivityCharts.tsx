import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { SensitivityScenario } from '../../../types'
import { formatCurrency, formatNumber } from '../../../lib/format'

type ScenarioKey = 'pessimistic' | 'base' | 'optimistic'

const SCENARIO_ORDER: ScenarioKey[] = ['pessimistic', 'base', 'optimistic']

// Fixed scenario -> color mapping, reused identically across all three mini
// charts and the shared legend, so a scenario's identity is always the same
// color regardless of which metric is being viewed.
const SCENARIO_COLOR: Record<ScenarioKey, string> = {
  pessimistic: '#d97706', // amber-600
  base: '#4f46e5', // indigo-600
  optimistic: '#059669', // emerald-600
}

const SCENARIO_LABEL: Record<ScenarioKey, string> = {
  pessimistic: 'Pessimistic',
  base: 'Base',
  optimistic: 'Optimistic',
}

interface MetricConfig {
  key: keyof SensitivityScenario
  label: string
  format: (v: number) => string
}

// NOTE ON SCOPE: the backend's sensitivity analysis
// (app/tools/financial_calc.py::run_sensitivity_analysis) only re-runs
// break-even math per scenario — it does not compute a per-scenario NPV or
// ROI% (those exist only as flat, non-scenario figures elsewhere in this
// section). The spec called for break-even/NPV/ROI% small multiples, but
// since NPV/ROI% aren't scenario-varying data, this renders the three
// metrics that actually vary per scenario instead of inventing numbers.
function buildMetrics(currency: string): MetricConfig[] {
  return [
    { key: 'break_even_months', label: 'Break-even (months)', format: (v) => formatNumber(v, 1) },
    { key: 'break_even_units', label: 'Break-even (units)', format: (v) => formatNumber(v, 0) },
    {
      key: 'monthly_revenue_at_break_even',
      label: 'Monthly revenue at break-even',
      format: (v) => formatCurrency(v, currency),
    },
  ]
}

export function SensitivityCharts({
  scenarios,
  currency,
  compact = false,
}: {
  scenarios: Record<ScenarioKey, SensitivityScenario> | undefined
  currency: string
  compact?: boolean
}) {
  if (!scenarios || SCENARIO_ORDER.some((key) => !scenarios[key])) {
    // Missing/malformed data — never crash, just skip the chart.
    return <p className="text-xs text-gray-400">Sensitivity scenario data unavailable.</p>
  }

  // Compact (chat): 3 side-by-side mini-charts in a ~448px-wide bubble is
  // illegible — show only the headline metric (break-even months) instead
  // of all 3. Same data, same building block, just fewer of them.
  const metrics = compact ? buildMetrics(currency).slice(0, 1) : buildMetrics(currency)

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1">
        {SCENARIO_ORDER.map((key) => (
          <span key={key} className="flex items-center gap-1.5 text-xs text-gray-600">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: SCENARIO_COLOR[key] }}
            />
            {SCENARIO_LABEL[key]}
            {scenarios[key]?.revenue_multiplier !== undefined && (
              <span className="text-gray-400">
                ({scenarios[key].revenue_multiplier}× revenue)
              </span>
            )}
          </span>
        ))}
      </div>
      <div className={compact ? 'grid grid-cols-1' : 'grid grid-cols-1 sm:grid-cols-3 gap-4'}>
        {metrics.map((metric) => {
          const data = SCENARIO_ORDER.map((key) => ({
            scenario: SCENARIO_LABEL[key],
            key,
            value: Number(scenarios[key]?.[metric.key] ?? 0),
          }))
          return (
            <div key={String(metric.key)}>
              <p className="mb-1 text-center text-[11px] font-medium text-gray-500">{metric.label}</p>
              <div dir="ltr" className={compact ? 'h-[90px]' : 'h-[130px]'}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e1e0d9" vertical={false} />
                    <XAxis dataKey="scenario" tick={{ fontSize: 10, fill: '#898781' }} stroke="#c3c2b7" />
                    <YAxis tick={{ fontSize: 10, fill: '#898781' }} width={40} stroke="#c3c2b7" />
                    <Tooltip formatter={(value) => metric.format(Number(value))} />
                    <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={compact ? 28 : 36}>
                      {data.map((d) => (
                        <Cell key={d.key} fill={SCENARIO_COLOR[d.key as ScenarioKey]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
