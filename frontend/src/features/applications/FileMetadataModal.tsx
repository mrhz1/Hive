import { Download, Search, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import { toast } from 'sonner'
import { useFileMetadata } from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'
import { applicationFilesApi } from '@/lib/api/resources'
import { metadataTone } from '@/schemas/applicationFile'

export type MetadataSubject = {
  id: string
  original_file_name: string
}

export function FileMetadataModal({
  file,
  deidentified = false,
  onClose,
}: {
  file: MetadataSubject
  /**
   * Read the redacted copy's metadata instead of the original's. The
   * two are different questions: what the document arrived carrying,
   * against what is left in the copy that leaves here.
   */
  deidentified?: boolean
  onClose: () => void
}) {
  const { data, isLoading, error } = useFileMetadata(file.id, deidentified)
  const [query, setQuery] = useState('')
  const [isExporting, setIsExporting] = useState(false)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const all = useMemo(() => Object.entries(data?.metadata ?? {}), [data])

  const entries = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return all
    return all.filter(
      ([name, value]) =>
        name.toLowerCase().includes(needle) ||
        String(value).toLowerCase().includes(needle)
    )
  }, [all, query])

  /** Exports exactly what the filter is showing, not the whole table. */
  async function exportFiltered() {
    setIsExporting(true)
    try {
      const blob = await applicationFilesApi.exportMetadata(
        file.id,
        query.trim() ? entries.map(([name]) => name) : undefined,
        deidentified
      )
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${deidentified ? 'deid-metadata' : 'metadata'}-${file.original_file_name}.xlsx`
      link.click()
      URL.revokeObjectURL(url)
    } catch (caught) {
      toast.error(
        caught instanceof ApiError ? caught.message : 'Could not export the metadata'
      )
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-[rgb(var(--background))]/80 p-4 backdrop-blur-sm sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label={`${
        deidentified ? 'De-identified metadata' : 'Metadata'
      } for ${file.original_file_name}`}
    >
      <div className="mx-auto flex h-full w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] shadow-xl">
        <div className="flex items-center justify-between gap-4 border-b border-[rgb(var(--border))] px-5 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-bold text-[rgb(var(--foreground))]">
              {file.original_file_name}
            </p>
            <p className="flex items-center gap-2 text-xs text-[rgb(var(--foreground-muted))]">
              <span>
                {deidentified
                  ? 'De-identified copy metadata'
                  : 'Document metadata'}
              </span>
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

        {all.length > 0 ? (
          <div className="border-b border-[rgb(var(--border))] px-5 py-3">
            <label className="relative block">
              <span className="sr-only">Search metadata</span>
              <Search
                className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[rgb(var(--foreground-muted))]"
                aria-hidden="true"
              />
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search field names and values"
                className="w-full rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--background))] py-2 pr-3 pl-9 text-sm"
              />
            </label>
            <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-[rgb(var(--foreground-muted))]">
                {query.trim()
                  ? `${entries.length} of ${all.length} fields`
                  : `${all.length} fields`}
              </p>
              <Button
                size="sm"
                variant="outline"
                disabled={entries.length === 0}
                isLoading={isExporting}
                leadingIcon={<Download className="size-3.5" aria-hidden="true" />}
                onClick={() => void exportFiltered()}
              >
                Export to Excel
              </Button>
            </div>
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-auto p-5">
          {isLoading ? (
            <div className="flex items-center gap-3 text-sm text-[rgb(var(--foreground-muted))]">
              <Spinner />
              Loading metadata
            </div>
          ) : error ? (
            <p className="text-sm text-[rgb(var(--foreground-muted))]">
              {/* The redacted copy's is read on demand, so a failure
                  here has a reason worth passing on -- 'not been
                  de-identified yet' is a different problem from an
                  original that carried nothing. */}
              {error instanceof ApiError
                ? error.message
                : 'No metadata was recorded for this file.'}
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
              {query.trim()
                ? `No field matches "${query}".`
                : 'This document carries no metadata.'}
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
