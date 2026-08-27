import { labelClass, textareaClass } from './styles'
import { NotesBox } from './NotesBox'
import type { WizardState } from './wizardState'

interface Props {
  state: WizardState
  update: (patch: Partial<WizardState>) => void
  note: string
  onNoteChange: (value: string) => void
}

export function Step1BusinessConcept({ state, update, note, onNoteChange }: Props) {
  return (
    <div className="space-y-5">
      <div>
        <label className={labelClass}>
          Business description <span className="text-red-500">*</span>
        </label>
        <textarea
          value={state.business_description}
          onChange={(e) => update({ business_description: e.target.value })}
          rows={4}
          placeholder="What does the business do? Describe the product or service."
          className={textareaClass}
        />
        <p className="mt-1 text-xs text-gray-400">
          {state.business_description.length} chars
          {state.business_description.length < 20 && state.business_description.length > 0
            ? ' — need at least 20'
            : ''}
        </p>
      </div>
      <div>
        <label className={labelClass}>Problem being solved</label>
        <textarea
          value={state.problem_statement}
          onChange={(e) => update({ problem_statement: e.target.value })}
          rows={3}
          placeholder="What problem does this solve for customers?"
          className={textareaClass}
        />
      </div>
      <div>
        <label className={labelClass}>Unique value proposition</label>
        <textarea
          value={state.unique_value_proposition}
          onChange={(e) => update({ unique_value_proposition: e.target.value })}
          rows={3}
          placeholder="What makes this different from the alternatives?"
          className={textareaClass}
        />
      </div>
      <NotesBox value={note} onChange={onNoteChange} />
    </div>
  )
}
