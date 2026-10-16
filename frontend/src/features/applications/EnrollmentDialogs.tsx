import { useEffect, useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/Button'
import { CheckboxField, TextAreaField } from '@/components/ui/Field'
import { usePermissions } from '@/hooks/useCurrentUser'
import {
  PURGE_CHECK,
  ENROLLMENT_CHECKS,
  type EnrollmentCheck,
} from '@/schemas/patientApplication'

function Dialog({
  title,
  description,
  onCancel,
  children,
}: {
  title: string
  description: ReactNode
  onCancel: () => void
  children: ReactNode
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onCancel])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgb(var(--background))]/80 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="w-full max-w-lg space-y-4 rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-5 shadow-xl">
        <div>
          <h2 className="text-sm font-bold">{title}</h2>
          <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
            {description}
          </p>
        </div>
        {children}
      </div>
    </div>
  )
}

function useChecks() {
  const [checked, setChecked] = useState<Set<EnrollmentCheck>>(new Set())
  const toggle = (key: EnrollmentCheck, on: boolean) =>
    setChecked((current) => {
      const next = new Set(current)
      if (on) next.add(key)
      else next.delete(key)
      return next
    })
  return { checked, toggle }
}

export function SubmitChecklistDialog({
  isBusy,
  onConfirm,
  onCancel,
}: {
  isBusy?: boolean
  onConfirm: (checklist: Record<EnrollmentCheck, boolean>) => void
  onCancel: () => void
}) {
  const { checked, toggle } = useChecks()
  const complete = checked.size === ENROLLMENT_CHECKS.length

  return (
    <Dialog
      title="Enrollment checklist"
      description="Confirm each point before submitting. If one fails, cancel and reject the application instead."
      onCancel={onCancel}
    >
      <div className="space-y-3">
        {ENROLLMENT_CHECKS.map((check) => (
          <CheckboxField
            key={check.key}
            label={check.label}
            checked={checked.has(check.key)}
            onChange={(event) => toggle(check.key, event.target.checked)}
          />
        ))}
      </div>

      <div className="flex flex-wrap justify-end gap-3">
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          isLoading={isBusy}
          disabled={!complete}
          title={complete ? undefined : 'Tick every point to submit'}
          onClick={() =>
            onConfirm(
              Object.fromEntries(
                ENROLLMENT_CHECKS.map((check) => [check.key, true])
              ) as Record<EnrollmentCheck, boolean>
            )
          }
        >
          Submit application
        </Button>
      </div>
    </Dialog>
  )
}

export function RejectApplicationDialog({
  title,
  description,
  isBusy,
  onConfirm,
  onCancel,
}: {
  title: string
  description: string
  isBusy?: boolean
  onConfirm: (failedChecks: EnrollmentCheck[], reason: string) => void
  onCancel: () => void
}) {
  const { can } = usePermissions()
  const canDelete = can('application:delete')
  const { checked, toggle } = useChecks()
  const [reason, setReason] = useState('')
  const [touched, setTouched] = useState(false)

  const notEligible = checked.has(PURGE_CHECK)
  const trimmed = reason.trim()
  const checksError =
    touched && checked.size === 0 ? 'Pick at least one point that failed' : undefined
  const reasonError = touched && !trimmed ? 'A reason is required' : undefined

  function confirm() {
    setTouched(true)
    if (checked.size === 0 || !trimmed) return
    onConfirm(
      ENROLLMENT_CHECKS.map((check) => check.key).filter((key) => checked.has(key)),
      trimmed
    )
  }

  return (
    <Dialog title={title} description={description} onCancel={onCancel}>
      <fieldset className="space-y-3">
        <legend className="mb-2 text-sm font-medium">What failed?</legend>
        {ENROLLMENT_CHECKS.map((check) => {
          const locked = check.key === PURGE_CHECK && !canDelete
          return (
            <CheckboxField
              key={check.key}
              label={check.label}
              description={
                locked
                  ? 'Needs permission to delete applications, since it deletes the documents'
                  : undefined
              }
              disabled={locked}
              checked={checked.has(check.key)}
              onChange={(event) => toggle(check.key, event.target.checked)}
            />
          )
        })}
        {checksError ? (
          <p className="text-xs font-medium text-rose-600 dark:text-rose-400">
            {checksError}
          </p>
        ) : null}
      </fieldset>

      {notEligible ? (
        <div
          role="alert"
          className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm"
        >
          <strong>A patient who is not eligible cannot be kept.</strong> Every document of
          this application, originals and de-identified copies, is deleted now and the
          submission has to start again. This cannot be undone; only the record of the
          application stays.
        </div>
      ) : null}

      <TextAreaField
        label="Reason"
        required
        rows={3}
        value={reason}
        placeholder="e.g. consent form not in the submission, or patient not eligible"
        error={reasonError}
        onChange={(event) => setReason(event.target.value)}
      />

      <div className="flex flex-wrap justify-end gap-3">
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button variant="danger" isLoading={isBusy} onClick={confirm}>
          {notEligible ? 'Reject and delete documents' : 'Reject application'}
        </Button>
      </div>
    </Dialog>
  )
}
