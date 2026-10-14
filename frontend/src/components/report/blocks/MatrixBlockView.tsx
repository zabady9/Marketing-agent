import {
  CartesianGrid,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import type { MatrixBlock } from '../../../types'
import { AXIS_STROKE, AXIS_TICK, COLORS, GRID_STROKE } from './palette'

// 2D positioning / perception map on a 0-10 grid with quadrant lines; the
// highlighted point (usually this business) stands out.
export function MatrixBlockView({ block, compact = false }: { block: MatrixBlock; compact?: boolean }) {
  const normal = block.points.filter((p) => !p.highlight)
  const highlighted = block.points.filter((p) => p.highlight)
  const height = compact ? 200 : 320
  return (
    <div dir="ltr">
      <div className="flex text-[10px] text-gray-400">
        <span className="w-10 shrink-0" />
        <span className="flex-1 text-center">{block.y_high}</span>
      </div>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 24, left: 0, bottom: 16 }}>
            <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" />
            <XAxis
              type="number"
              dataKey="x"
              domain={[0, 10]}
              ticks={[0, 5, 10]}
              tick={{ fontSize: 10, fill: AXIS_TICK }}
              stroke={AXIS_STROKE}
              label={{ value: block.x_axis, position: 'insideBottom', offset: -8, fontSize: 11, fill: '#4b5563' }}
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={[0, 10]}
              ticks={[0, 5, 10]}
              tick={{ fontSize: 10, fill: AXIS_TICK }}
              stroke={AXIS_STROKE}
              width={40}
              label={{ value: block.y_axis, angle: -90, position: 'insideLeft', fontSize: 11, fill: '#4b5563' }}
            />
            <ZAxis range={[90, 90]} />
            <ReferenceLine x={5} stroke="#9ca3af" />
            <ReferenceLine y={5} stroke="#9ca3af" />
            <Tooltip cursor={false} formatter={(v) => Number(v).toFixed(1)} />
            <Scatter data={normal} fill={COLORS[0]}>
              <LabelList dataKey="label" position="top" fontSize={compact ? 9 : 11} fill="#374151" />
            </Scatter>
            <Scatter data={highlighted} fill={COLORS[1]} shape="star">
              <LabelList dataKey="label" position="top" fontSize={compact ? 10 : 12} fontWeight={600} fill="#b45309" />
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <div className="flex justify-between ps-10 pe-6 text-[10px] text-gray-400">
        <span>{block.x_low}</span>
        <span>{block.y_low && `↓ ${block.y_low}`}</span>
        <span>{block.x_high}</span>
      </div>
    </div>
  )
}
