import { useQueryClient } from '@tanstack/react-query'
import { ChevronRight, File, Folder, FolderDown, HardDriveDownload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Badge, Card } from '@/components/ui/Misc'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import {
  useCarbonCheck,
  useCarbonCopy,
  useCarbonFolder,
  useCarbonStatus,
} from '@/hooks/useResources'
import { errorMessage } from '@/hooks/createCrudHooks'
import { queryKeys } from '@/lib/queryKeys'
import { formatFileSize } from '@/schemas/applicationFile'
import type { CarbonCheck, CarbonEntry, CarbonStatus } from '@/schemas/intake'
import { ProgressBar } from './IntakeProgressPanel'

const titleClass =
  'text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase'
const labelClass = 'text-xs text-[rgb(var(--foreground-muted))]'

function Breadcrumbs({
  share,
  path,
  onOpen,
}: {
  share: string
  path: string
  onOpen: (path: string) => void
}) {
  const parts = path ? path.split('/') : []
  return (
    <nav aria-label="Carbon folder" className="flex flex-wrap items-center gap-1 text-sm">
      <button
        type="button"
        className="font-mono font-semibold text-[rgb(var(--primary))] hover:underline"
        onClick={() => onOpen('')}
      >
        {share}
      </button>
      {parts.map((part, index) => {
        const target = parts.slice(0, index + 1).join('/')
        const last = index === parts.length - 1
        return (
          <span key={target} className="flex items-center gap-1">
            <ChevronRight
              className="size-3.5 text-[rgb(var(--foreground-muted))]"
              aria-hidden="true"
            />
            {last ? (
              <span className="font-semibold">{part}</span>
            ) : (
              <button
                type="button"
                className="text-[rgb(var(--primary))] hover:underline"
                onClick={() => onOpen(target)}
              >
                {part}
              </button>
            )}
          </span>
        )
      })}
    </nav>
  )
}

function EntryRow({
  entry,
  checked,
  disabled,
  onToggle,
  onOpen,
}: {
  entry: CarbonEntry
  checked: boolean
  disabled: boolean
  onToggle: () => void
  onOpen: () => void
}) {
  const Icon = entry.is_dir ? Folder : File
  return (
    <li className="flex items-center gap-3 border-t border-[rgb(var(--border))] px-1 py-2 first:border-0">
      <input
        type="checkbox"
        className="size-4 accent-teal-600"
        checked={checked}
        disabled={disabled}
        onChange={onToggle}
        aria-label={`Select ${entry.name}`}
      />
      <Icon
        className={`size-4 shrink-0 ${entry.is_dir ? 'text-amber-500' : 'text-[rgb(var(--foreground-muted))]'}`}
        aria-hidden="true"
      />
      {entry.is_dir ? (
        <button
          type="button"
          className="min-w-0 flex-1 truncate text-left text-sm font-medium hover:underline"
          onClick={onOpen}
          title={`Open ${entry.name}`}
        >
          {entry.name}
        </button>
      ) : (
        <span className="min-w-0 flex-1 truncate text-sm">{entry.name}</span>
      )}
      {!entry.is_dir && (
        <span className={`${labelClass} tabular-nums`}>{formatFileSize(entry.size)}</span>
      )}
    </li>
  )
}

function CopyProgress({ state }: { state: CarbonStatus }) {
  const percent = state.total ? ((state.done + state.failed) / state.total) * 100 : 0
  const finished = !state.running && state.finished_at
  return (
    <div
      role="status"
      className="space-y-2 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] p-3 text-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold">
          {state.running ? 'Copying to incoming...' : 'Last copy from Carbon'}
        </span>
        <span className="tabular-nums">
          {state.done.toLocaleString()} of {state.total.toLocaleString()} files ·{' '}
          {formatFileSize(state.bytes_done)} of {formatFileSize(state.bytes_total)}
        </span>
      </div>
      {state.running && <ProgressBar percent={percent} />}
      {state.running && state.current ? (
        <p className="truncate font-mono text-xs text-[rgb(var(--foreground-muted))]">
          {state.current}
        </p>
      ) : null}
      {finished ? (
        <p>
          Copied {state.done.toLocaleString()}
          {state.failed ? `, ${state.failed.toLocaleString()} failed` : ''}
          {state.skipped ? `, ${state.skipped.toLocaleString()} were already there` : ''}
          {state.started_by ? ` (by ${state.started_by})` : ''}. Click{' '}
          <strong>Start de-identification</strong> above to process them.
        </p>
      ) : null}
      {state.errors.length > 0 && (
        <ul className="space-y-0.5 font-mono text-xs text-rose-600 dark:text-rose-400">
          {state.errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function CarbonImportPanel() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [path, setPath] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [checked, setChecked] = useState<CarbonCheck | null>(null)
  const folder = useCarbonFolder(path, open)
  const status = useCarbonStatus(open)
  const check = useCarbonCheck()
  const copy = useCarbonCopy()
  const running = Boolean(status.data?.running)

  const wasRunning = useRef(running)
  useEffect(() => {
    if (wasRunning.current && !running) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.intake.status() })
    }
    wasRunning.current = running
  }, [running, queryClient])

  const choose = (next: string[]) => {
    setSelected(next)
    setChecked(null)
  }

  const toggle = (entryPath: string) =>
    choose(
      selected.includes(entryPath)
        ? selected.filter((p) => p !== entryPath)
        : [...selected, entryPath]
    )

  const coveredByParent = (entryPath: string) =>
    selected.some((p) => p !== entryPath && entryPath.startsWith(`${p}/`))

  if (!open) {
    return (
      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className={`flex items-center gap-2 ${titleClass}`}>
              <HardDriveDownload className="size-3.5" aria-hidden="true" /> Copy from
              Carbon
            </h2>
            <p className="mt-1 text-sm text-[rgb(var(--foreground-muted))]">
              Pick folders on the Carbon share and copy them into the incoming folder.
            </p>
          </div>
          <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
            Browse Carbon
          </Button>
        </div>
      </Card>
    )
  }

  const entries = folder.data?.entries ?? []
  const visibleSelectable = entries.filter((e) => !coveredByParent(e.path))
  const allHere =
    visibleSelectable.length > 0 &&
    visibleSelectable.every((e) => selected.includes(e.path))

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className={`flex items-center gap-2 ${titleClass}`}>
          <HardDriveDownload className="size-3.5" aria-hidden="true" /> Copy from Carbon
        </h2>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Close
        </Button>
      </div>

      {status.data && (status.data.running || status.data.finished_at) ? (
        <CopyProgress state={status.data} />
      ) : null}

      <Breadcrumbs share={folder.data?.share ?? 'Carbon'} path={path} onOpen={setPath} />

      <div className="rounded-lg border border-[rgb(var(--border))]">
        {folder.isLoading ? (
          <div className="p-4">
            <Spinner size="sm" label="Opening folder" />
          </div>
        ) : folder.isError ? (
          <div
            role="alert"
            className="space-y-2 p-4 text-sm text-rose-600 dark:text-rose-400"
          >
            <p>{errorMessage(folder.error, 'Could not open the Carbon share')}</p>
            <Button size="sm" variant="outline" onClick={() => void folder.refetch()}>
              Try again
            </Button>
          </div>
        ) : entries.length === 0 ? (
          <p className="p-4 text-sm text-[rgb(var(--foreground-muted))]">
            This folder is empty.
          </p>
        ) : (
          <>
            <label className="flex items-center gap-3 border-b border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] px-3 py-2 text-xs font-semibold">
              <input
                type="checkbox"
                className="size-4 accent-teal-600"
                checked={allHere}
                onChange={() => {
                  const here = visibleSelectable.map((e) => e.path)
                  choose(
                    allHere
                      ? selected.filter((p) => !here.includes(p))
                      : [...new Set([...selected, ...here])]
                  )
                }}
              />
              Select everything in this folder
            </label>
            <ul className="max-h-96 overflow-y-auto px-2">
              {entries.map((entry) => (
                <EntryRow
                  key={entry.path}
                  entry={entry}
                  checked={selected.includes(entry.path) || coveredByParent(entry.path)}
                  disabled={coveredByParent(entry.path)}
                  onToggle={() => toggle(entry.path)}
                  onOpen={() => setPath(entry.path)}
                />
              ))}
            </ul>
          </>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
          <Badge tone={selected.length ? 'info' : 'neutral'}>
            {selected.length} selected
          </Badge>
          {selected.length > 0 && (
            <>
              <span className="truncate font-mono text-xs text-[rgb(var(--foreground-muted))]">
                {selected.slice(0, 3).join(', ')}
                {selected.length > 3 ? ` +${selected.length - 3}` : ''}
              </span>
              <Button size="sm" variant="ghost" onClick={() => choose([])}>
                Clear
              </Button>
            </>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={!selected.length || running}
            isLoading={check.isPending}
            onClick={() =>
              void check
                .mutateAsync(selected)
                .then(setChecked)
                .catch(() => setChecked(null))
            }
          >
            Check
          </Button>
          <Button
            size="sm"
            disabled={!checked || checked.files === 0 || running}
            isLoading={copy.isPending}
            leadingIcon={<FolderDown className="size-3.5" aria-hidden="true" />}
            onClick={() =>
              void copy
                .mutateAsync(selected)
                .then(() => choose([]))
                .catch(() => undefined)
            }
          >
            {checked ? `Copy ${checked.files.toLocaleString()} files` : 'Copy'}
          </Button>
        </div>
      </div>

      {checked ? (
        <p role="status" className="text-sm">
          <strong>{checked.files.toLocaleString()}</strong> new files (
          {formatFileSize(checked.bytes)})
          {checked.skipped
            ? ` · ${checked.skipped.toLocaleString()} already in incoming or processed, skipped`
            : ''}
          {checked.files === 0 ? '. Nothing new to copy.' : '.'}
        </p>
      ) : selected.length > 0 ? (
        <p className={labelClass}>Click Check to count the new files before copying.</p>
      ) : null}
    </Card>
  )
}
