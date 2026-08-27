import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { InputForm, type FieldErrorInfo } from '../components/InputForm'
import { createProject, FieldError } from '../api'
import type { StartStudyRequest } from '../types'

export function QuestionnairePage() {
  const navigate = useNavigate()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [fieldError, setFieldError] = useState<FieldErrorInfo | null>(null)

  async function handleSubmit(payload: StartStudyRequest) {
    setIsSubmitting(true)
    setFieldError(null)
    try {
      const projectId = await createProject(payload)
      navigate(`/projects/${projectId}`)
    } catch (err) {
      if (err instanceof FieldError) {
        // Handled inline by InputForm via the fieldError prop — don't rethrow,
        // or InputForm's own catch would also show a redundant generic error.
        setFieldError({ field: err.field, reason: err.message })
        return
      }
      throw err
    } finally {
      setIsSubmitting(false)
    }
  }

  return <InputForm onSubmit={handleSubmit} isSubmitting={isSubmitting} fieldError={fieldError} />
}
