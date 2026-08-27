import { labelClass, textareaClass } from './styles'
import { NotesBox } from './NotesBox'
import { TagInput } from './TagInput'
import type { WizardState } from './wizardState'

interface Props {
  state: WizardState
  update: (patch: Partial<WizardState>) => void
  note: string
  onNoteChange: (value: string) => void
}

export function Step6CompetitionRisks({ state, update, note, onNoteChange }: Props) {
  return (
    <div className="space-y-5">
      <div>
        <label className={labelClass}>Known competitors</label>
        <TagInput
          values={state.competitors}
          onChange={(v) => update({ competitors: v })}
          placeholder="e.g. Acme Corp — press Enter to add"
        />
      </div>
      <div>
        <label className={labelClass}>Risks or concerns, in your own words</label>
        <textarea
          value={state.founder_risks}
          onChange={(e) => update({ founder_risks: e.target.value })}
          rows={4}
          placeholder="What worries you about this business? This feeds directly into the risk assessment."
          className={textareaClass}
        />
      </div>
      <NotesBox value={note} onChange={onNoteChange} />
    </div>
  )
}
