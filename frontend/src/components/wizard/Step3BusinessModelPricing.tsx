import { inputClass, labelClass } from './styles'
import { NotesBox } from './NotesBox'
import type { WizardFieldError, WizardState } from './wizardState'

interface Props {
  state: WizardState
  update: (patch: Partial<WizardState>) => void
  note: string
  onNoteChange: (value: string) => void
  fieldError?: WizardFieldError | null
}

export function Step3BusinessModelPricing({
  state,
  update,
  note,
  onNoteChange,
  fieldError,
}: Props) {
  const priceError = fieldError?.field === 'pricing_unit_price' ? fieldError.reason : null

  return (
    <div className="space-y-5">
      <div>
        <label className={labelClass}>Business model type</label>
        <input
          type="text"
          value={state.business_model_type}
          onChange={(e) => update({ business_model_type: e.target.value })}
          placeholder="e.g. SaaS, marketplace, D2C, subscription"
          className={inputClass}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelClass}>
            Unit price <span className="text-red-500">*</span>
          </label>
          <div className="flex gap-2">
            <input
              type="number"
              min="0"
              step="any"
              value={state.pricing_unit_price}
              onChange={(e) => update({ pricing_unit_price: e.target.value })}
              placeholder="e.g. 99"
              className={`flex-1 rounded-lg border px-3.5 py-2.5 text-sm outline-none transition-colors ${
                priceError
                  ? 'border-red-400 focus:border-red-500 focus:ring-1 focus:ring-red-500'
                  : 'border-gray-300 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500'
              }`}
            />
            <input
              type="text"
              value={state.pricing_currency}
              onChange={(e) => update({ pricing_currency: e.target.value.toUpperCase() })}
              placeholder="USD"
              maxLength={3}
              className="w-20 rounded-lg border border-gray-300 px-2 py-2.5 text-sm text-center font-mono focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
            />
          </div>
          {priceError && <p className="mt-1.5 text-xs text-red-600">{priceError}</p>}
          <p className="mt-1 text-xs text-gray-400">Required to build a financial model.</p>
        </div>
        <div>
          <label className={labelClass}>Pricing model</label>
          <input
            type="text"
            value={state.pricing_model}
            onChange={(e) => update({ pricing_model: e.target.value })}
            placeholder="e.g. subscription, one-time, usage-based"
            className={inputClass}
          />
        </div>
      </div>
      <div>
        <label className={labelClass}>Expected monthly sales</label>
        <input
          type="number"
          min="0"
          step="any"
          value={state.expected_monthly_sales}
          onChange={(e) => update({ expected_monthly_sales: e.target.value })}
          placeholder="e.g. 500 units/subscribers per month"
          className={inputClass}
        />
      </div>
      <NotesBox value={note} onChange={onNoteChange} />
    </div>
  )
}
