import { Download, X } from 'lucide-react'
import { useEffect } from 'react'
import { Button } from '@/components/ui/Button'
import { formatFileSize, type PatientFile } from '@/schemas/patientFile'

/**
 * In-app document viewer.
 *
 * The bytes are fetched through the API client (the endpoint needs an
 * identity header, so the browser cannot simply navigate to it) and
 * handed to an iframe as a blob URL. Rendering here rather than in a
 * popup avoids both the popup blocker and the cross-window blob
 * navigation that Chromium does not reliably honour -- and keeps the
 * user inside the dashboard.
 */
export function FileViewerModal({
  file,
  blobUrl,
  isDeidentified,
  onClose,
}: {
  file: PatientFile
  blobUrl: string
  isDeidentified: boolean
  onClose: () => void
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const displayName = isDeidentified
    ? (file.deidentified_file_name ?? file.sanitized_file_name)
    : file.original_file_name

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-[rgb(var(--background))]/80 p-4 backdrop-blur-sm sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label={`Viewing ${displayName}`}
    >
      <div className="mx-auto flex h-full w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] shadow-xl">
        <div className="flex items-center justify-between gap-4 border-b border-[rgb(var(--border))] px-5 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-bold text-[rgb(var(--foreground))]">
              {displayName}
            </p>
            <p className="text-xs text-[rgb(var(--foreground-muted))]">
              {file.mime_type} · {formatFileSize(file.file_size)}
              {isDeidentified ? ' · de-identified copy' : ''}
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {/* A download attribute on a blob URL works where opening a
                blob in another window does not. */}
            <a href={blobUrl} download={displayName}>
              <Button
                variant="outline"
                size="sm"
                leadingIcon={<Download className="size-3.5" aria-hidden="true" />}
              >
                Download
              </Button>
            </a>
            <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close viewer">
              <X className="size-4" aria-hidden="true" />
            </Button>
          </div>
        </div>

        <iframe
          src={blobUrl}
          title={`Preview of ${displayName}`}
          className="min-h-0 w-full flex-1 bg-[rgb(var(--background-secondary))]"
        />
      </div>
    </div>
  )
}
