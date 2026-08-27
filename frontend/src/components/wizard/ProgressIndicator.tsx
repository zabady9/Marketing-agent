import { STEP_TITLES } from './wizardState'

export function ProgressIndicator({ step }: { step: number }) {
  return (
    <div className="mb-8">
      <div className="flex items-center gap-1.5">
        {STEP_TITLES.map((title, i) => (
          <div
            key={title}
            className={`h-2 flex-1 rounded-full transition-colors ${
              i <= step ? 'bg-indigo-600' : 'bg-gray-200'
            }`}
          />
        ))}
      </div>
      <p className="mt-2 text-xs font-medium text-gray-500">
        Step {step + 1} of {STEP_TITLES.length}: {STEP_TITLES[step]}
      </p>
    </div>
  )
}
