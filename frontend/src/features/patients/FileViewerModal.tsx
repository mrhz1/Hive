import {
  ChevronLeft,
  ChevronRight,
  Download,
  Eye,
  ShieldCheck,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { usePermissions } from '@/hooks/useCurrentUser'
import { ApiError } from '@/lib/api/client'
import {
  applicationFilesApi,
  deidentifiedFilesApi,
} from '@/lib/api/resources'
import {
  formatFileSize,
  previewKind,
  type WordPreview,
} from '@/schemas/applicationFile'

export type ViewableFile = {
  mime_type: string
  file_size: number
  file_extension: string
  original_file_name: string
  sanitized_file_name?: string
  deidentified_file_name?: string | null

  de_identified_file_path?: string | null
}

type Side = 'original' | 'deidentified'

export type ViewerSource = 'application' | 'library'

function errorText(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return fallback
}

type FrameState =
  | { status: 'loading' }
  | { status: 'ready'; url: string }
  | { status: 'error'; message: string }

function DicomFrame({
  fileId,
  source,
  isDeidentified,
  frame,
  alt,
  onFrameCount,
}: {
  fileId: string
  source: ViewerSource
  isDeidentified: boolean
  frame: number
  alt: string
  onFrameCount: (frames: number) => void
}) {
  const [state, setState] = useState<FrameState>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    let objectUrl: string | null = null

    const load =
      source === 'library'
        ? deidentifiedFilesApi.previewImage(fileId, frame)
        : applicationFilesApi.previewImage(fileId, frame, isDeidentified)

    load
      .then((preview) => {
        if (cancelled) {
          URL.revokeObjectURL(preview.url)
          return
        }
        objectUrl = preview.url
        setState({ status: 'ready', url: preview.url })
        onFrameCount(preview.frames)
      })
      .catch((caught) => {
        if (!cancelled) {
          setState({
            status: 'error',
            message: errorText(caught, 'Could not render this image'),
          })
        }
      })

    return () => {
      cancelled = true

      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [fileId, frame, isDeidentified, source, onFrameCount])

  if (state.status === 'error') {
    return <ViewerMessage tone="error">{state.message}</ViewerMessage>
  }

  return (
    <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto bg-black p-4">
      {state.status === 'loading' ? (
        <Spinner size="lg" label="Rendering image" />
      ) : (
        <img
          src={state.url}
          alt={alt}
          className="max-h-full max-w-full object-contain"
        />
      )}
    </div>
  )
}

function DicomViewer({
  fileId,
  source,
  isDeidentified,
  name,
}: {
  fileId: string
  source: ViewerSource
  isDeidentified: boolean
  name: string
}) {
  const [frame, setFrame] = useState(0)
  const [frames, setFrames] = useState(1)

  const onFrameCount = useCallback((count: number) => setFrames(count), [])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <DicomFrame
        key={frame}
        fileId={fileId}
        source={source}
        isDeidentified={isDeidentified}
        frame={frame}
        alt={`${name}${frames > 1 ? `, frame ${frame + 1} of ${frames}` : ''}`}
        onFrameCount={onFrameCount}
      />

      {frames > 1 ? (
        <div className="flex items-center justify-center gap-3 border-t border-[rgb(var(--border))] px-5 py-2">
          <Button
            size="sm"
            variant="outline"
            aria-label="Previous frame"
            disabled={frame === 0}
            onClick={() => setFrame((current) => Math.max(0, current - 1))}
          >
            <ChevronLeft className="size-4" aria-hidden="true" />
          </Button>
          <span
            className="text-xs font-semibold tabular-nums text-[rgb(var(--foreground-muted))]"
            aria-live="polite"
          >
            Frame {frame + 1} of {frames}
          </span>
          <Button
            size="sm"
            variant="outline"
            aria-label="Next frame"
            disabled={frame >= frames - 1}
            onClick={() =>
              setFrame((current) => Math.min(frames - 1, current + 1))
            }
          >
            <ChevronRight className="size-4" aria-hidden="true" />
          </Button>
        </div>
      ) : null}
    </div>
  )
}

function WordViewer({
  fileId,
  source,
  isDeidentified,
}: {
  fileId: string
  source: ViewerSource
  isDeidentified: boolean
}) {
  const [document, setDocument] = useState<WordPreview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const load =
      source === 'library'
        ? deidentifiedFilesApi.previewText(fileId)
        : applicationFilesApi.previewText(fileId, isDeidentified)

    load
      .then((body) => {
        if (!cancelled) setDocument(body)
      })
      .catch((caught) => {
        if (!cancelled)
          setError(errorText(caught, 'Could not read this document'))
      })

    return () => {
      cancelled = true
    }
  }, [fileId, isDeidentified, source])

  if (error) return <ViewerMessage tone="error">{error}</ViewerMessage>
  if (!document) {
    return (
      <ViewerMessage>
        <Spinner size="md" label="Reading document" />
      </ViewerMessage>
    )
  }

  const isEmpty = document.blocks.length === 0 && document.tables.length === 0

  return (
    <div className="min-h-0 flex-1 overflow-auto bg-[rgb(var(--background-secondary))] p-6">
      <div className="mx-auto max-w-3xl space-y-4 rounded-lg bg-[rgb(var(--surface))] p-8 shadow-sm">
        {isEmpty ? (
          <p className="text-sm text-[rgb(var(--foreground-muted))]">
            This document has no text in it.
          </p>
        ) : null}

        {document.blocks.map((block, index) =>
          block.kind === 'heading' ? (
            <h3
              key={index}
              className="text-lg font-bold text-[rgb(var(--foreground))]"
            >
              {block.text}
            </h3>
          ) : (
            <p
              key={index}
              className="text-sm leading-relaxed text-[rgb(var(--foreground))]"
            >
              {block.text}
            </p>
          )
        )}

        {document.tables.map((table, tableIndex) => (
          <div key={`table-${tableIndex}`} className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <tbody>
                {table.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((cell, cellIndex) => (
                      <td
                        key={cellIndex}
                        className="border border-[rgb(var(--border))] px-3 py-1.5"
                      >
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}

        {document.truncated ? (
          <p className="border-t border-[rgb(var(--border))] pt-4 text-xs text-[rgb(var(--foreground-muted))]">
            This preview is truncated. Download the file to read all of it.
          </p>
        ) : null}
      </div>
    </div>
  )
}

function ViewerMessage({
  children,
  tone = 'muted',
}: {
  children: React.ReactNode
  tone?: 'muted' | 'error'
}) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center p-8">
      <p
        className={
          tone === 'error'
            ? 'max-w-md text-center text-sm text-rose-600 dark:text-rose-400'
            : 'max-w-md text-center text-sm text-[rgb(var(--foreground-muted))]'
        }
      >
        {children}
      </p>
    </div>
  )
}

export function FileViewerModal({
  file,
  fileId,
  blobUrl,
  isDeidentified,
  source = 'application',
  canViewOriginal = true,
  onClose,
}: {
  file: ViewableFile
  fileId: string

  blobUrl?: string | null
  isDeidentified: boolean
  source?: ViewerSource

  canViewOriginal?: boolean
  onClose: () => void
}) {
  const close = useCallback(() => onClose(), [onClose])

  const { can } = usePermissions()
  const canDownload = can('files:download')
  const [isDownloading, setIsDownloading] = useState(false)

  const [side, setSide] = useState<Side>(
    isDeidentified ? 'deidentified' : 'original'
  )
  const showingDeidentified = side === 'deidentified'

  // Both copies hang off one file id -- the row holds both paths -- so the
  // viewer can flip between them rather than being closed and reopened.
  // Only the library has a single side to show.
  const canCompare =
    source === 'application' &&
    canViewOriginal &&
    (Boolean(file.de_identified_file_path) || isDeidentified)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    window.document.addEventListener('keydown', onKeyDown)
    return () => window.document.removeEventListener('keydown', onKeyDown)
  }, [close])

  const displayName = showingDeidentified
    ? (file.deidentified_file_name ??
      file.sanitized_file_name ??
      file.original_file_name)
    : file.original_file_name

  const extension =
    showingDeidentified && ['doc', 'docx'].includes(file.file_extension)
      ? 'docx'
      : file.file_extension
  const kind = previewKind(extension)

  // The caller pre-fetched the blob for the side it opened on; anything
  // else this viewer fetches itself, and revokes what it made.
  const ownUrls = useRef<string[]>([])
  const [pdfUrls, setPdfUrls] = useState<Partial<Record<Side, string>>>(() =>
    blobUrl ? { [isDeidentified ? 'deidentified' : 'original']: blobUrl } : {}
  )
  // Per side, so switching back to a side that loaded fine is not shown
  // the other side's failure -- and nothing has to be cleared in an effect.
  const [pdfErrors, setPdfErrors] = useState<Partial<Record<Side, string>>>({})
  const pdfError = pdfErrors[side] ?? null

  useEffect(
    () => () => {
      ownUrls.current.forEach((url) => URL.revokeObjectURL(url))
      ownUrls.current = []
    },
    []
  )

  const pdfUrl = pdfUrls[side] ?? null

  useEffect(() => {
    if (kind !== 'pdf' || pdfUrl || pdfError) return

    let cancelled = false

    const wanted = side
    applicationFilesApi
      .fetchContent(fileId, wanted === 'deidentified')
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        if (cancelled) {
          URL.revokeObjectURL(url)
          return
        }
        ownUrls.current.push(url)
        setPdfUrls((current) => ({ ...current, [wanted]: url }))
      })
      .catch((caught) => {
        if (!cancelled) {
          setPdfErrors((current) => ({
            ...current,
            [wanted]: errorText(caught, 'Could not open this file'),
          }))
        }
      })

    return () => {
      cancelled = true
    }
  }, [kind, pdfUrl, pdfError, fileId, side])

  async function saveACopy() {
    setIsDownloading(true)
    try {
      const blob =
        source === 'library'
          ? await deidentifiedFilesApi.fetchContent(fileId, true)
          : await applicationFilesApi.fetchContent(
              fileId,
              showingDeidentified,
              true
            )

      const url = URL.createObjectURL(blob)
      const anchor = window.document.createElement('a')
      anchor.href = url
      anchor.download = displayName

      window.document.body.append(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (caught) {
      toast.error(errorText(caught, 'Could not download this file'))
    } finally {
      setIsDownloading(false)
    }
  }

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
              {showingDeidentified ? ' · de-identified copy' : ''}
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {canCompare ? (
              <div
                className="flex items-center rounded-lg border border-[rgb(var(--border))] p-0.5"
                role="group"
                aria-label="Which copy to show"
              >
                <SideButton
                  icon={<Eye className="size-3.5" aria-hidden="true" />}
                  label="Original"
                  isActive={side === 'original'}
                  onSelect={() => setSide('original')}
                />
                <SideButton
                  icon={<ShieldCheck className="size-3.5" aria-hidden="true" />}
                  label="De-identified"
                  isActive={side === 'deidentified'}
                  onSelect={() => setSide('deidentified')}
                />
              </div>
            ) : null}

            {canDownload ? (
              <Button
                variant="outline"
                size="sm"
                isLoading={isDownloading}
                leadingIcon={<Download className="size-3.5" aria-hidden="true" />}
                onClick={() => void saveACopy()}
              >
                Download
              </Button>
            ) : null}
            <Button variant="ghost" size="sm" onClick={close} aria-label="Close viewer">
              <X className="size-4" aria-hidden="true" />
            </Button>
          </div>
        </div>

        {kind === 'image' ? (
          <DicomViewer
            key={side}
            fileId={fileId}
            source={source}
            isDeidentified={showingDeidentified}
            name={displayName}
          />
        ) : kind === 'text' ? (
          <WordViewer
            key={side}
            fileId={fileId}
            source={source}
            isDeidentified={showingDeidentified}
          />
        ) : kind === 'pdf' ? (
          pdfError ? (
            <ViewerMessage tone="error">{pdfError}</ViewerMessage>
          ) : pdfUrl ? (
            <iframe
              src={pdfUrl}
              title={`Preview of ${displayName}`}
              className="min-h-0 w-full flex-1 bg-[rgb(var(--background-secondary))]"
            />
          ) : (
            <ViewerMessage>
              <Spinner size="md" label="Opening document" />
            </ViewerMessage>
          )
        ) : (
          <ViewerMessage>
            {`'${file.file_extension || 'This'}' files cannot be shown here. `}
            {canDownload ? 'Use Download to open it locally.' : ''}
          </ViewerMessage>
        )}
      </div>
    </div>
  )
}

function SideButton({
  icon,
  label,
  isActive,
  onSelect,
}: {
  icon: React.ReactNode
  label: string
  isActive: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={isActive}
      onClick={onSelect}
      className={
        'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold transition-colors ' +
        (isActive
          ? 'bg-[rgb(var(--background-secondary))] text-[rgb(var(--foreground))]'
          : 'text-[rgb(var(--foreground-muted))] hover:text-[rgb(var(--foreground))]')
      }
    >
      {icon}
      {label}
    </button>
  )
}
