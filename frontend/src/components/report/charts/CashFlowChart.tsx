import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { CashFlowCalcOutput, CashFlowFigure } from '../../../types'
import { formatCurrency } from '../../../lib/format'

export function CashFlowChart({
  cashFlow,
  currency,
  compact = false,
}: {
  cashFlow: CashFlowFigure
  currency: string
  compact?: boolean
}) {
  const output = cashFlow.calculation_trace?.output as CashFlowCalcOutput | undefined
  const series = output?.cash_position_by_month

  if (!Array.isArray(series) || series.length === 0 || series.some((v) => typeof v !== 'number')) {
    // Malformed/missing series — never crash, fall back to the two headline
    // numbers everyone actually needs.
    return (
      <div className="grid grid-cols-2 gap-3 text-center">
        <div>
          <p className="text-sm font-semibold text-gray-900">
            {cashFlow.payback_month === null ? 'Not reached' : `Month ${cashFlow.payback_month}`}
          </p>
          <p className="text-[10px] text-gray-500">Payback</p>
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-900">
            {formatCurrency(cashFlow.final_position, currency)}
          </p>
          <p className="text-[10px] text-gray-500">Final cash position</p>
        </div>
      </div>
    )
  }

  const data = series.map((value, month) => ({ month, value }))
  const paybackPoint =
    cashFlow.payback_month !== null ? data.find((d) => d.month === cashFlow.payback_month) : undefined

  return (
    <div dir="ltr" className={compact ? 'h-[110px]' : 'h-[200px]'}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e1e0d9" />
          <XAxis
            dataKey="month"
            tick={{ fontSize: 10, fill: '#898781' }}
            stroke="#c3c2b7"
            {...(compact
              ? {}
              : { label: { value: 'Month', position: 'insideBottom', offset: -2, fontSize: 10, fill: '#898781' } })}
          />
          <YAxis
            tick={{ fontSize: 10, fill: '#898781' }}
            stroke="#c3c2b7"
            tickFormatter={(v: number) => formatCurrency(v, currency, 0)}
            width={compact ? 50 : 70}
            {...(compact ? { tickCount: 3 } : {})}
          />
          <Tooltip
            formatter={(value) => formatCurrency(Number(value), currency)}
            labelFormatter={(m) => `Month ${m}`}
          />
          <ReferenceLine y={0} stroke="#c3c2b7" />
          {paybackPoint && (
            <ReferenceLine
              x={paybackPoint.month}
              stroke="#059669"
              strokeDasharray="4 4"
              label={compact ? undefined : { value: 'Payback', position: 'top', fontSize: 10, fill: '#059669' }}
            />
          )}
          <Line type="monotone" dataKey="value" stroke="#4f46e5" strokeWidth={2} dot={false} />
          {paybackPoint && (
            <ReferenceDot x={paybackPoint.month} y={paybackPoint.value} r={compact ? 3 : 5} fill="#059669" stroke="#fff" />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
