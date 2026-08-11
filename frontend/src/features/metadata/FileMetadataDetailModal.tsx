import { Search, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Misc'
import { metadataTone } from '@/schemas/applicationFile'
import { metadataEntries, type FileMetadataRow } from '@/schemas/fileMetadata'

/**
 * Everything one row carries.
 *
 * The browse table already holds the whole blob, so unlike the per-file
 * modal in features/applications this fetches nothing -- it is a reader
 * for a row that is already on screen.
 */
export function FileMetadataDetailModal({
  row,
  onClose,
}: {
  row: FileMetadataRow
  onClose: () => void
}) {
  const [query, setQuery] = useState('')

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const all = useMemo(() => metadataEntries(row), [row])

  const entries = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return all
    return all.filter(
      ([name, value]) =>
        name.toLowerCase().includes(needle) ||
        value.toLowerCase().includes(needle)
    )
  }, [all, query])

  const title = row.file_name ?? row.file_id

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-[rgb(var(--background))]/80 p-4 backdrop-blur-sm sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label={`Metadata for ${title}`}
    >
      <div className="mx-auto flex h-full w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] shadow-xl">
        <div className="flex items-center justify-between gap-4 border-b border-[rgb(var(--border))] px-5 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-bold text-[rgb(var(--foreground))]">
              {title}
            </p>
            <p className="flex flex-wrap items-center gap-2 text-xs text-[rgb(var(--foreground-muted))]">
              {row.patient_id ? <span>{row.patient_id}</span> : null}
              <Badge tone="neutral">{row.file_type || 'file'}</Badge>
              <Badge tone={metadataTone(row.status)}>{row.status}</Badge>
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
              <span className="sr-only">Search these fields</span>
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
            <p className="mt-1.5 text-xs text-[rgb(var(--foreground-muted))]">
              {query.trim()
                ? `${entries.length} of ${all.length} fields`
                : `${all.length} fields`}
            </p>
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-auto p-5">
          {row.status === 'failed' ? (
            <div className="space-y-2">
              <p className="text-sm text-[rgb(var(--foreground))]">
                This document could not be read.
              </p>
              <p className="font-mono text-xs break-words text-[rgb(var(--foreground-muted))]">
                {row.error}
              </p>
            </div>
          ) : row.status === 'unsupported' ? (
            <p className="text-sm text-[rgb(var(--foreground-muted))]">
              Metadata is only read from PDF, DICOM and Word documents.
            </p>
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
