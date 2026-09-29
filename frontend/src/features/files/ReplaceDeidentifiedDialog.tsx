import { ShieldCheck, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { useUploadDeidentifiedFile } from '@/hooks/useResources'
import type { RejectedFile } from '@/schemas/rejection'

/**
 * Attach a better redacted copy in place of the one that was rejected.
 *
 * The upload keeps the file's id and its place in the application; the
 * server sends the file back to `pending` review, since nobody has looked
 * at the new bytes yet. That is also what takes the row off this queue.
 */
export function ReplaceDeidentifiedDialog({
  file,
  onClose,
  onReplaced,
}: {
  file: RejectedFile
  onClose: () => void
  onReplaced?: () => void
}) {
  const upload = useUploadDeidentifiedFile()
  const inputRef = useRef<HTMLInputElement>(null)
  const [chosen, setChosen] = useState<File | null>(null)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.document.addEventListener('keydown', onKeyDown)
    return () => window.document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  async function submit() {
    if (!chosen) return
    try {
      await upload.mutateAsync({
        patientId: file.patient_id,
        file: chosen,
        replacesFileId: file.id,
      })
      onReplaced?.()
      onClose()
    } catch {
      // The hook toasts its own message.
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgb(var(--background))]/80 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={`Replace the de-identified copy of ${file.original_file_name}`}
    >
      <div className="w-full max-w-lg overflow-hidden rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] shadow-xl">
        <div className="flex items-start justify-between gap-4 border-b border-[rgb(var(--border))] px-5 py-3">
          <div className="min-w-0">
            <p className="text-sm font-bold text-[rgb(var(--foreground))]">
              Replace the de-identified copy
            </p>
            <p className="truncate text-xs text-[rgb(var(--foreground-muted))]">
              {file.original_file_name} · {file.patient_id}
            </p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            aria-label="Close"
          >
            <X className="size-4" aria-hidden="true" />
          </Button>
        </div>

        <div className="space-y-4 p-5">
          {file.review_note ? (
            <div className="rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] p-3">
              <p className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
                Why it was rejected
              </p>
              <p className="mt-1 text-sm text-[rgb(var(--foreground))]">
                {file.review_note}
              </p>
            </div>
          ) : null}

          <p className="text-xs text-[rgb(var(--foreground-muted))]">
            The new copy keeps this file's id and its place in the
            application, and goes back to <strong>pending</strong> review --
            nobody has checked the replacement yet. The rejection note is
            kept in the audit log. PDF, DICOM or Word.
          </p>

          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.dcm,.dicom,.doc,.docx"
            aria-label="Replacement de-identified document"
            disabled={upload.isPending}
            onChange={(event) => setChosen(event.target.files?.[0] ?? null)}
            className="w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-[rgb(var(--surface-muted))] file:px-3 file:py-2 file:text-sm"
          />

          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={!chosen}
              isLoading={upload.isPending}
              leadingIcon={<ShieldCheck className="size-3.5" aria-hidden="true" />}
              onClick={() => void submit()}
            >
              Replace
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
