import { inputClass, labelClass } from './styles'
import { NotesBox } from './NotesBox'
import { TagInput } from './TagInput'
import type { WizardState } from './wizardState'

interface Props {
  state: WizardState
  update: (patch: Partial<WizardState>) => void
  note: string
  onNoteChange: (value: string) => void
}

export function Step5TeamOperations({ state, update, note, onNoteChange }: Props) {
  return (
    <div className="space-y-5">
      <div>
        <label className={labelClass}>Team size</label>
        <input
          type="number"
          min="0"
          step="1"
          value={state.team_size}
          onChange={(e) => update({ team_size: e.target.value })}
          placeholder="Current or planned headcount"
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass}>Key roles needed</label>
        <TagInput
          values={state.key_roles_needed}
          onChange={(v) => update({ key_roles_needed: v })}
          placeholder="e.g. head of sales — press Enter to add"
        />
      </div>
      <div>
        <label className={labelClass}>Sales / marketing channels</label>
        <TagInput
          values={state.marketing_channels}
          onChange={(v) => update({ marketing_channels: v })}
          placeholder="e.g. Instagram, cold outreach — press Enter to add"
        />
      </div>
      <NotesBox value={note} onChange={onNoteChange} />
    </div>
  )
}
