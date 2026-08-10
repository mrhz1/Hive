import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { TextAreaField } from '@/components/ui/Field'

export function ReasonDialog({
  title,
  description,
  confirmLabel,
  placeholder,
  isBusy,
  onConfirm,
  onCancel,
}: {
  title: string
  description: string
  confirmLabel: string
  placeholder?: string
  isBusy?: boolean
  onConfirm: (reason: string) => void
  onCancel: () => void
}) {
  const [reason, setReason] = useState('')
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onCancel])

  const trimmed = reason.trim()
  const error = touched && !trimmed ? 'A reason is required' : undefined

  function confirm() {
    setTouched(true)
    if (trimmed) onConfirm(trimmed)
  }

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

        <TextAreaField
          label="Reason"
          required
          autoFocus
          rows={4}
          value={reason}
          placeholder={placeholder}
          error={error}
          onChange={(event) => setReason(event.target.value)}
          onBlur={() => setTouched(true)}
        />

        <div className="flex flex-wrap justify-end gap-3">
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="danger" isLoading={isBusy} onClick={confirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
