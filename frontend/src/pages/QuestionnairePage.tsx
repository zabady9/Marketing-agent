import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { WizardForm, type WizardFieldError } from '../components/wizard/WizardForm'
import { createProject, FieldError } from '../api'
import type { StartStudyRequest } from '../types'

export function QuestionnairePage() {
  const navigate = useNavigate()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [fieldError, setFieldError] = useState<WizardFieldError | null>(null)

  async function handleSubmit(payload: StartStudyRequest) {
    setIsSubmitting(true)
    setFieldError(null)
    try {
      const projectId = await createProject(payload)
      navigate(`/projects/${projectId}`)
    } catch (err) {
      if (err instanceof FieldError) {
        // Handled inline by WizardForm via the fieldError prop — don't rethrow,
        // or WizardForm's own catch would also show a redundant generic error.
        setFieldError({ field: err.field, reason: err.message })
        return
      }
      throw err
    } finally {
      setIsSubmitting(false)
    }
  }

  return <WizardForm onSubmit={handleSubmit} isSubmitting={isSubmitting} fieldError={fieldError} />
}
