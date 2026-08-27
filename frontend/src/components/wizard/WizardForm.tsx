import { useEffect, useState } from 'react'
import type { StartStudyRequest } from '../../types'
import { ProgressIndicator } from './ProgressIndicator'
import { Step1BusinessConcept } from './Step1BusinessConcept'
import { Step2TargetMarket } from './Step2TargetMarket'
import { Step3BusinessModelPricing } from './Step3BusinessModelPricing'
import { Step4CostsInvestment } from './Step4CostsInvestment'
import { Step5TeamOperations } from './Step5TeamOperations'
import { Step6CompetitionRisks } from './Step6CompetitionRisks'
import { Step7GoalsHorizon } from './Step7GoalsHorizon'
import {
  PRICING_STEP,
  STEP_COUNT,
  buildSubmitPayload,
  createInitialWizardState,
  validateStep,
  type WizardFieldError,
} from './wizardState'

export type { WizardFieldError }

interface Props {
  onSubmit: (payload: StartStudyRequest) => Promise<void>
  isSubmitting: boolean
  // Server-side field-scoped error (e.g. a bypassed-client price hard block) —
  // shown inline on the pricing step rather than as a generic message.
  fieldError?: WizardFieldError | null
}

export function WizardForm({ onSubmit, isSubmitting, fieldError }: Props) {
  const [state, setState] = useState(createInitialWizardState)
  const [step, setStep] = useState(0)
  const [stepError, setStepError] = useState<string | null>(null)

  useEffect(() => {
    if (fieldError?.field === 'pricing_unit_price') {
      setStep(PRICING_STEP)
    }
  }, [fieldError])

  function update(patch: Partial<typeof state>) {
    setState((prev) => ({ ...prev, ...patch }))
  }

  function setNote(value: string) {
    setState((prev) => {
      const notes = [...prev.notes]
      notes[step] = value
      return { ...prev, notes }
    })
  }

  function goNext() {
    const error = validateStep(step, state)
    if (error) {
      setStepError(error)
      return
    }
    setStepError(null)
    setStep((s) => Math.min(s + 1, STEP_COUNT - 1))
  }

  function goBack() {
    setStepError(null)
    setStep((s) => Math.max(s - 1, 0))
  }

  async function handleSubmit() {
    const error = validateStep(step, state)
    if (error) {
      setStepError(error)
      return
    }
    setStepError(null)
    await onSubmit(buildSubmitPayload(state))
  }

  const stepProps = {
    state,
    update,
    note: state.notes[step],
    onNoteChange: setNote,
  }
  const isLastStep = step === STEP_COUNT - 1

  return (
    <div className="min-h-screen bg-gray-50 flex items-start justify-center pt-16 px-4">
      <div className="w-full max-w-2xl">
        <div className="mb-8">
          <h1 className="text-3xl font-semibold text-gray-900 tracking-tight">
            Feasibility Study
          </h1>
          <p className="mt-2 text-gray-500 text-sm">
            Answer a few short steps about your business idea. The AI pipeline runs market
            sizing, competitive analysis, financial modeling, and risk assessment once you submit.
          </p>
        </div>

        <ProgressIndicator step={step} />

        <div className="rounded-xl border border-gray-200 bg-white p-6">
          {step === 0 && <Step1BusinessConcept {...stepProps} />}
          {step === 1 && <Step2TargetMarket {...stepProps} />}
          {step === 2 && <Step3BusinessModelPricing {...stepProps} fieldError={fieldError} />}
          {step === 3 && <Step4CostsInvestment {...stepProps} />}
          {step === 4 && <Step5TeamOperations {...stepProps} />}
          {step === 5 && <Step6CompetitionRisks {...stepProps} />}
          {step === 6 && <Step7GoalsHorizon {...stepProps} />}
        </div>

        {stepError && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {stepError}
          </div>
        )}

        <div className="mt-6 flex items-center justify-between">
          <button
            type="button"
            onClick={goBack}
            disabled={step === 0}
            className="rounded-lg px-4 py-2.5 text-sm font-medium text-gray-600 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            ← Back
          </button>
          {isLastStep ? (
            <button
              type="button"
              onClick={handleSubmit}
              disabled={isSubmitting}
              className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isSubmitting ? 'Starting study…' : 'Run feasibility study'}
            </button>
          ) : (
            <button
              type="button"
              onClick={goNext}
              className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 transition-colors"
            >
              Next →
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
