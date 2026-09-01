import type { ReactNode } from 'react'

export interface DataTableColumn<T> {
  header: string
  render: (row: T, index: number) => ReactNode
  className?: string
}

// Generic full-detail table — used for competitors and risks so nothing gets
// truncated to a top-N slice. `rowId`/`rowClassName` let a caller (e.g. the
// risk matrix) highlight/scroll to a specific row.
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  rowId,
  rowClassName,
}: {
  columns: DataTableColumn<T>[]
  rows: T[]
  rowKey: (row: T, index: number) => string
  rowId?: (row: T, index: number) => string
  rowClassName?: (row: T, index: number) => string
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-gray-400">None reported.</p>
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full divide-y divide-gray-200 text-start text-sm">
        <thead className="bg-gray-50">
          <tr>
            {columns.map((col) => (
              <th
                key={col.header}
                className="px-3 py-2 text-start text-xs font-semibold text-gray-500 whitespace-nowrap"
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {rows.map((row, i) => (
            <tr
              key={rowKey(row, i)}
              id={rowId?.(row, i)}
              className={`align-top transition-colors ${rowClassName?.(row, i) ?? ''}`}
            >
              {columns.map((col) => (
                <td key={col.header} className={`px-3 py-2.5 text-gray-700 ${col.className ?? ''}`}>
                  {col.render(row, i)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
