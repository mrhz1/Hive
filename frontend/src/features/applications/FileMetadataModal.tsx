import { X } from 'lucide-react'
import { useEffect } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import { useFileMetadata } from '@/hooks/useResources'
import {
  metadataTone,
  type ApplicationFile,
} from '@/schemas/applicationFile'

export function FileMetadataModal({
  file,
  onClose,
}: {
  file: ApplicationFile
  onClose: () => void
}) {
  const { data, isLoading, error } = useFileMetadata(file.id)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const entries = Object.entries(data?.metadata ?? {})

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-[rgb(var(--background))]/80 p-4 backdrop-blur-sm sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label={`Metadata for ${file.original_file_name}`}
    >
      <div className="mx-auto flex h-full w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] shadow-xl">
        <div className="flex items-center justify-between gap-4 border-b border-[rgb(var(--border))] px-5 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-bold text-[rgb(var(--foreground))]">
              {file.original_file_name}
            </p>
            <p className="flex items-center gap-2 text-xs text-[rgb(var(--foreground-muted))]">
              <span>Document metadata</span>
              {data ? (
                <>
                  <Badge tone="neutral">{data.file_type}</Badge>
                  <Badge tone={metadataTone(data.status)}>{data.status}</Badge>
                </>
              ) : null}
            </p>
          </div>

          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            aria-label="Close metadata"
          >
            <X className="size-4" aria-hidden="true" />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto p-5">
          {isLoading ? (
            <div className="flex items-center gap-3 text-sm text-[rgb(var(--foreground-muted))]">
              <Spinner />
              Loading metadata
            </div>
          ) : error ? (
            <p className="text-sm text-[rgb(var(--foreground-muted))]">
              No metadata was recorded for this file.
            </p>
          ) : data?.status === 'unsupported' ? (
            <p className="text-sm text-[rgb(var(--foreground-muted))]">
              Metadata is only read from PDF, DICOM and Word documents.
            </p>
          ) : data?.status === 'failed' ? (
            <div className="space-y-2">
              <p className="text-sm text-[rgb(var(--foreground))]">
                This document could not be read.
              </p>
              <p className="font-mono text-xs break-words text-[rgb(var(--foreground-muted))]">
                {data.error}
              </p>
            </div>
          ) : entries.length === 0 ? (
            <p className="text-sm text-[rgb(var(--foreground-muted))]">
              This document carries no metadata.
            </p>
          ) : (
            <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-[minmax(0,14rem)_1fr]">
              {entries.map(([name, value]) => (
                <div key={name} className="contents">
                  <dt className="truncate font-mono text-xs text-[rgb(var(--foreground-muted))] sm:pt-0.5">
                    {name}
                  </dt>
                  {/* break-words, not truncate: a UID or an XMP blob is
                      long and unguessable from its first characters. */}
                  <dd className="mb-2 text-sm break-words text-[rgb(var(--foreground))] sm:mb-0">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>
    </div>
  )
}
