import { useEffect, useRef } from 'react'
import { Button } from './ui/Button'

export type ConfirmDeleteModalProps = {
  open: boolean
  /** Capitalised entity name, e.g. 'User' -- used in the heading. */
  entityLabel: string
  /** Human name of the record, so the user can confirm the target. */
  targetName?: string | undefined
  isDeleting?: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function ConfirmDeleteModal({
  open,
  entityLabel,
  targetName,
  isDeleting = false,
  onCancel,
  onConfirm,
}: ConfirmDeleteModalProps) {
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return

    panelRef.current?.focus()

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isDeleting) onCancel()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, isDeleting, onCancel])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgb(var(--background))]/60 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
      aria-describedby="modal-description"
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="animate-in fade-in zoom-in-95 w-full max-w-md rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-6 shadow-xl outline-none"
      >
        <h2 id="modal-title" className="text-lg font-bold text-[rgb(var(--foreground))]">
          Delete {entityLabel} Record
        </h2>

        <p
          id="modal-description"
          className="mt-2 text-sm text-[rgb(var(--foreground-muted))]"
        >
          Are you sure you want to delete{' '}
          <span className="font-semibold text-[rgb(var(--foreground))]">
            {targetName ?? `this ${entityLabel.toLowerCase()}`}
          </span>
          ? This action is permanent and cannot be undone.
        </p>

        <div className="mt-6 flex justify-end gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={onCancel}
            disabled={isDeleting}
          >
            Cancel
          </Button>

          <Button
            type="button"
            variant="danger"
            onClick={onConfirm}
            isLoading={isDeleting}
          >
            {isDeleting ? 'Deleting…' : 'Confirm Delete'}
          </Button>
        </div>
      </div>
    </div>
  )
}
