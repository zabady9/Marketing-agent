import { useState } from 'react'
import type { StartStudyRequest } from '../types'

interface Props {
  onSubmit: (payload: StartStudyRequest) => Promise<void>
  isSubmitting: boolean
}

export function InputForm({ onSubmit, isSubmitting }: Props) {
  const [rawInput, setRawInput] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [unitPrice, setUnitPrice] = useState('')
  const [pricingCurrency, setPricingCurrency] = useState('USD')
  const [capex, setCapex] = useState('')
  const [opex, setOpex] = useState('')
  const [horizonYears, setHorizonYears] = useState('3')
  const [outputLanguage, setOutputLanguage] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (rawInput.trim().length < 20) {
      setError('Please describe your business idea in at least 20 characters.')
      return
    }
    setError(null)

    const payload: StartStudyRequest = {
      raw_user_input: rawInput.trim(),
      analysis_horizon_years: parseInt(horizonYears, 10) || 3,
    }
    if (unitPrice) payload.pricing_unit_price = parseFloat(unitPrice)
    if (pricingCurrency) payload.pricing_currency = pricingCurrency
    if (capex) payload.capex_amount = parseFloat(capex)
    if (opex) payload.opex_monthly_amount = parseFloat(opex)
    if (outputLanguage) payload.output_language = outputLanguage

    try {
      await onSubmit(payload)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start study. Is the backend running?')
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-start justify-center pt-16 px-4">
      <div className="w-full max-w-2xl">
        <div className="mb-8">
          <h1 className="text-3xl font-semibold text-gray-900 tracking-tight">
            Feasibility Study
          </h1>
          <p className="mt-2 text-gray-500 text-sm">
            Describe your business idea. The AI pipeline runs market sizing, competitive
            analysis, financial modeling, and risk assessment — streamed live as results arrive.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Business idea <span className="text-red-500">*</span>
            </label>
            <textarea
              value={rawInput}
              onChange={(e) => setRawInput(e.target.value)}
              rows={6}
              placeholder="Describe your business idea in detail. Include the product or service, target customers, geography, pricing if you have it, and any known competitors. The more detail you provide, the less the system needs to estimate."
              className="w-full rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none resize-none transition-colors"
            />
            <p className="mt-1 text-xs text-gray-400">
              {rawInput.length} chars{rawInput.length < 20 && rawInput.length > 0 ? ' — need at least 20' : ''}
            </p>
          </div>

          <div>
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-1.5 text-sm text-indigo-600 hover:text-indigo-700 font-medium"
            >
              <span className={`transition-transform ${showAdvanced ? 'rotate-90' : ''}`}>▶</span>
              Advanced options
            </button>

            {showAdvanced && (
              <div className="mt-3 grid grid-cols-2 gap-4 p-4 bg-white rounded-lg border border-gray-200">
                <div className="col-span-2 text-xs text-gray-500 -mb-1">
                  These override LLM extraction. Leave blank to let the system extract from your description above.
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Unit price
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="number"
                      min="0"
                      step="any"
                      value={unitPrice}
                      onChange={(e) => setUnitPrice(e.target.value)}
                      placeholder="e.g. 99"
                      className="flex-1 rounded border border-gray-300 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
                    />
                    <input
                      type="text"
                      value={pricingCurrency}
                      onChange={(e) => setPricingCurrency(e.target.value.toUpperCase())}
                      placeholder="USD"
                      maxLength={3}
                      className="w-16 rounded border border-gray-300 px-2 py-1.5 text-sm text-center font-mono focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Analysis horizon (years)
                  </label>
                  <select
                    value={horizonYears}
                    onChange={(e) => setHorizonYears(e.target.value)}
                    className="w-full rounded border border-gray-300 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none bg-white"
                  >
                    {[1, 2, 3, 4, 5].map((n) => (
                      <option key={n} value={n}>{n} year{n > 1 ? 's' : ''}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Capex (one-time investment)
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    value={capex}
                    onChange={(e) => setCapex(e.target.value)}
                    placeholder="e.g. 50000"
                    className="w-full rounded border border-gray-300 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Monthly opex
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    value={opex}
                    onChange={(e) => setOpex(e.target.value)}
                    placeholder="e.g. 8000"
                    className="w-full rounded border border-gray-300 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
                  />
                </div>

                <div className="col-span-2">
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Output language override (BCP-47)
                  </label>
                  <input
                    type="text"
                    value={outputLanguage}
                    onChange={(e) => setOutputLanguage(e.target.value)}
                    placeholder="e.g. ar, en, fr — leave blank to auto-detect"
                    className="w-full rounded border border-gray-300 px-2.5 py-1.5 text-sm font-mono focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
                  />
                </div>
              </div>
            )}
          </div>

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={isSubmitting || rawInput.trim().length < 20}
            className="w-full rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isSubmitting ? 'Starting study…' : 'Run feasibility study'}
          </button>
        </form>
      </div>
    </div>
  )
}
