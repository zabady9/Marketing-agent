import { inputClass, labelClass, selectClass } from './styles'
import { NotesBox } from './NotesBox'
import type { WizardState } from './wizardState'

interface Props {
  state: WizardState
  update: (patch: Partial<WizardState>) => void
  note: string
  onNoteChange: (value: string) => void
}

export function Step4CostsInvestment({ state, update, note, onNoteChange }: Props) {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelClass}>Capex (one-time investment)</label>
          <input
            type="number"
            min="0"
            step="any"
            value={state.capex_amount}
            onChange={(e) => update({ capex_amount: e.target.value })}
            placeholder="e.g. 50000"
            className={inputClass}
          />
        </div>
        <div>
          <label className={labelClass}>Monthly opex</label>
          <input
            type="number"
            min="0"
            step="any"
            value={state.opex_monthly_amount}
            onChange={(e) => update({ opex_monthly_amount: e.target.value })}
            placeholder="e.g. 8000"
            className={inputClass}
          />
        </div>
      </div>
      <p className="text-xs text-gray-400 -mt-2">
        Leave either blank to let the system estimate it via web research.
      </p>
      <div>
        <label className={labelClass}>Funding source</label>
        <select
          value={state.funding_source}
          onChange={(e) =>
            update({ funding_source: e.target.value as WizardState['funding_source'] })
          }
          className={selectClass}
        >
          <option value="">Not specified</option>
          <option value="self-funded">Self-funded</option>
          <option value="loan">Loan</option>
          <option value="investors">Investors</option>
          <option value="other">Other</option>
        </select>
      </div>
      <NotesBox value={note} onChange={onNoteChange} />
    </div>
  )
}
