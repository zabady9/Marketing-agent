import { inputClass, labelClass, selectClass } from './styles'
import { NotesBox } from './NotesBox'
import type { WizardState } from './wizardState'

interface Props {
  state: WizardState
  update: (patch: Partial<WizardState>) => void
  note: string
  onNoteChange: (value: string) => void
}

export function Step7GoalsHorizon({ state, update, note, onNoteChange }: Props) {
  return (
    <div className="space-y-5">
      <div>
        <label className={labelClass}>Analysis horizon</label>
        <select
          value={state.analysis_horizon_years}
          onChange={(e) => update({ analysis_horizon_years: e.target.value })}
          className={selectClass}
        >
          {[1, 2, 3, 4, 5].map((n) => (
            <option key={n} value={n}>
              {n} year{n > 1 ? 's' : ''}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelClass}>Output language override (BCP-47)</label>
        <input
          type="text"
          value={state.output_language}
          onChange={(e) => update({ output_language: e.target.value })}
          placeholder="e.g. ar, en, fr — leave blank to auto-detect"
          className={`${inputClass} font-mono`}
        />
      </div>
      <div>
        <label className={labelClass}>Primary goal for this study</label>
        <select
          value={state.study_goal}
          onChange={(e) => update({ study_goal: e.target.value as WizardState['study_goal'] })}
          className={selectClass}
        >
          <option value="">Not specified</option>
          <option value="validate idea">Validate the idea</option>
          <option value="secure funding">Secure funding</option>
          <option value="internal planning">Internal planning</option>
          <option value="other">Other</option>
        </select>
      </div>
      <NotesBox value={note} onChange={onNoteChange} />
    </div>
  )
}
