// Native <details> disclosure — no new dependency needed. Renders nothing
// when `methodology` is falsy/empty, which is the common case today (the
// backend's methodology strings are populated in a later stage) — that's
// expected, not a bug. When methodology text does exist, it's shown
// alongside the calc trace's inputs/output for financial figures, or alone
// for market/competitor/risk entities that don't carry a full CalcTrace.
export function MethodologyDisclosure({
  methodology,
  inputs,
  output,
}: {
  methodology?: string
  inputs?: Record<string, unknown>
  output?: Record<string, unknown>
}) {
  if (!methodology) return null

  return (
    <details className="mt-1 text-xs text-gray-500">
      <summary className="cursor-pointer select-none font-medium text-gray-500 hover:text-gray-700">
        Methodology
      </summary>
      <div className="mt-1.5 space-y-1.5 ps-3">
        <p>{methodology}</p>
        {inputs && Object.keys(inputs).length > 0 && (
          <div>
            <p className="font-medium text-gray-400">Inputs</p>
            <pre className="whitespace-pre-wrap break-all text-[11px] text-gray-500">
              {JSON.stringify(inputs, null, 2)}
            </pre>
          </div>
        )}
        {output && Object.keys(output).length > 0 && (
          <div>
            <p className="font-medium text-gray-400">Output</p>
            <pre className="whitespace-pre-wrap break-all text-[11px] text-gray-500">
              {JSON.stringify(output, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </details>
  )
}
