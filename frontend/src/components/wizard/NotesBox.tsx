import { smallLabelClass, textareaClass } from './styles'

interface Props {
  value: string
  onChange: (value: string) => void
}

export function NotesBox({ value, onChange }: Props) {
  return (
    <div className="pt-2 border-t border-gray-100">
      <label className={smallLabelClass}>Anything else we should know? (optional)</label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={2}
        placeholder="Add any nuance or detail that doesn't fit the fields above — the AI will factor it in."
        className={textareaClass}
      />
    </div>
  )
}
