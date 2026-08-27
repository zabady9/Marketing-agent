import { inputClass, labelClass, selectClass } from './styles'
import { NotesBox } from './NotesBox'
import type { WizardState } from './wizardState'

interface Props {
  state: WizardState
  update: (patch: Partial<WizardState>) => void
  note: string
  onNoteChange: (value: string) => void
}

export function Step2TargetMarket({ state, update, note, onNoteChange }: Props) {
  return (
    <div className="space-y-5">
      <div>
        <label className={labelClass}>Target customer description</label>
        <input
          type="text"
          value={state.target_market_description}
          onChange={(e) => update({ target_market_description: e.target.value })}
          placeholder="e.g. busy urban professionals aged 25-40"
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass}>Geography</label>
        <input
          type="text"
          value={state.target_market_geography}
          onChange={(e) => update({ target_market_geography: e.target.value })}
          placeholder="e.g. United States, Southeast Asia"
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass}>Target market type</label>
        <select
          value={state.target_market_type}
          onChange={(e) =>
            update({ target_market_type: e.target.value as WizardState['target_market_type'] })
          }
          className={selectClass}
        >
          <option value="">Not specified</option>
          <option value="B2C">B2C — selling to consumers</option>
          <option value="B2B">B2B — selling to businesses</option>
        </select>
      </div>
      <NotesBox value={note} onChange={onNoteChange} />
    </div>
  )
}
