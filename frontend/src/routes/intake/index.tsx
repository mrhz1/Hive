import { createFileRoute } from '@tanstack/react-router'
import { Copy, Download, GitCompareArrows, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable, type Column } from '@/components/DataTable'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/Field'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { IntakeProgressPanel } from '@/features/intake/IntakeProgressPanel'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import {
  useIntakeCounts,
  useIntakePage,
  useResolveIntakeConflict,
  useRetryIntakeFile,
} from '@/hooks/useResources'
import { intakeApi } from '@/lib/api/resources'
import { formatFileSize } from '@/schemas/applicationFile'
import {
  intakeSearchText,
  filesToText,
  type IntakeCounts,
  type IntakeFile,
} from '@/schemas/intake'

export const Route = createFileRoute('/intake/')({
  component: IntakePage,
})

type View = 'conflict' | 'skipped' | 'failed' | 'queued' | 'done'

type ViewOption = {
  id: View
  label: string
  hint: string
  tone: 'danger' | 'warning' | 'neutral' | 'success' | 'info'
  empty: string
}

const PAGE_SIZE = 500

const VIEWS: ViewOption[] = [
  {
    id: 'conflict',
    label: 'Conflicts',
    hint: 'The path and the file name point to different patients. Choose which one is right.',
    tone: 'danger',
    empty: 'No conflicts.',
  },
  {
    id: 'skipped',
    label: 'Skipped',
    hint: 'No patient code, or a format we cannot redact. Fix these at source and push them again.',
    tone: 'warning',
    empty: 'Nothing was skipped.',
  },
  {
    id: 'failed',
    label: 'Failed',
    hint: 'Redaction was attempted and did not work. The reason is on each row. Retry it here, or push a corrected file to the same place.',
    tone: 'danger',
    empty: 'Nothing has failed.',
  },
  {
    id: 'queued',
    label: 'Waiting',
    hint: 'Placed under a code and waiting for a worker.',
    tone: 'info',
    empty: 'Nothing here.',
  },
  {
    id: 'done',
    label: 'De-identified',
    hint: 'Redacted into the de_identified mirror, ready to be picked for an application.',
    tone: 'success',
    empty: 'Nothing here.',
  },
]

function getCount(counts: IntakeCounts | undefined, view: View): number {
  if (!counts) return 0
  if (view === 'queued') return counts.queued + counts.processing
  return counts[view]
}

function IntakePage() {
  useDocumentTitle('Intake')

  const counts = useIntakeCounts()
  const [view, setView] = useState<View>('conflict')
  const [limit, setLimit] = useState(PAGE_SIZE)
  const [search, setSearch] = useState('')
  const files = useIntakePage(view, limit)
  const resolve = useResolveIntakeConflict()
  const retry = useRetryIntakeFile()

  const current = VIEWS.find((v) => v.id === view) ?? VIEWS[0]!

  const allRows = files.data?.rows ?? []
  const searchText = search.trim().toLowerCase()
  const visible = searchText
    ? allRows.filter((file) => intakeSearchText(file).includes(searchText))
    : allRows

  function changeView(newView: View) {
    setView(newView)
    setSearch('')
    setLimit(PAGE_SIZE)
  }

  async function downloadAll() {
    try {
      const blob = await intakeApi.exportCsv(view)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `intake-${view}.csv`
      document.body.append(link)
      link.click()
      link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch {
      toast.error('Could not download the list')
    }
  }

  async function copyList() {
    try {
      await navigator.clipboard.writeText(filesToText(visible))
      toast.success(`Copied ${visible.length} path${visible.length === 1 ? '' : 's'}`)
    } catch {
      toast.error('Could not reach the clipboard')
    }
  }

  const columns: Array<Column<IntakeFile>> = [
    {
      id: 'path',
      header: 'File',
      cell: (file) => (
        <div className="min-w-0">
          <span className="block truncate font-semibold">{file.file_name}</span>
          <span
            className="block truncate font-mono text-xs text-[rgb(var(--foreground-muted))]"
            title={file.source_path}
          >
            {file.source_path}
          </span>
        </div>
      ),
      sortValue: (file) => file.source_path,
    },
    {
      id: 'code',
      header: 'Code',
      cell: (file) => {
        if (file.patient_code) {
          return <span className="font-mono text-sm font-bold">{file.patient_code}</span>
        }
        if (view === 'conflict') {
          return (
            <span className="font-mono text-xs">
              path <strong>{file.path_code}</strong> · name{' '}
              <strong>{file.name_code}</strong>
            </span>
          )
        }
        return <span className="text-xs text-[rgb(var(--foreground-muted))]">none</span>
      },
      sortValue: (file) => file.patient_code ?? file.path_code ?? '',
    },
    {
      id: 'type',
      header: 'Type',
      cell: (file) => (
        <div className="whitespace-nowrap">
          <Badge tone="neutral">{file.file_extension || 'none'}</Badge>
          <span className="ml-2 text-xs text-[rgb(var(--foreground-muted))]">
            {formatFileSize(file.file_size)}
          </span>
        </div>
      ),
      sortValue: (file) => file.file_extension,
    },
    view === 'done'
      ? {
          id: 'output',
          header: 'Redacted copy',
          cell: (file) => (
            <span className="font-mono text-xs">{file.output_name ?? '--'}</span>
          ),
          sortValue: (file) => file.output_name ?? '',
        }
      : {
          id: 'why',
          header: 'Why',
          cell: (file) => (
            <div className="max-w-sm text-sm">
              {file.reason && <span className="font-semibold">{file.reason}</span>}
              {file.detail && (
                <span className="block text-xs text-[rgb(var(--foreground-muted))]">
                  {file.detail}
                </span>
              )}
            </div>
          ),
          sortValue: (file) => file.reason ?? '',
        },
  ]

  function conflictActions(file: IntakeFile) {
    const choices = []
    if (file.path_code) choices.push({ code: file.path_code, source: 'path' })
    if (file.name_code) choices.push({ code: file.name_code, source: 'name' })

    return (
      <Can permission="application:update">
        {choices.map((choice) => (
          <Button
            key={choice.code}
            size="sm"
            variant="outline"
            aria-label={`File ${file.file_name} under ${choice.code}`}
            isLoading={
              resolve.isPending &&
              resolve.variables?.fileId === file.id &&
              resolve.variables.code === choice.code
            }
            leadingIcon={<GitCompareArrows className="size-3.5" aria-hidden="true" />}
            onClick={() => resolve.mutate({ fileId: file.id, code: choice.code })}
          >
            {choice.code}
            <span className="ml-1 text-[10px] font-normal opacity-70">
              {choice.source}
            </span>
          </Button>
        ))}
      </Can>
    )
  }

  function retryAction(file: IntakeFile) {
    return (
      <Can permission="application:update">
        <Button
          size="sm"
          variant="outline"
          aria-label={`Retry ${file.file_name}`}
          isLoading={retry.isPending && retry.variables === file.id}
          leadingIcon={<RotateCcw className="size-3.5" aria-hidden="true" />}
          onClick={() => retry.mutate(file.id)}
        >
          Retry
        </Button>
      </Can>
    )
  }

  let rowActions
  if (view === 'conflict') rowActions = conflictActions
  if (view === 'failed') rowActions = retryAction

  const canCopy = view === 'skipped' || view === 'failed'
  const canDownload = canCopy || view === 'conflict'
  const total = files.data?.total ?? 0
  const loaded = files.data?.rows.length ?? 0

  return (
    <RequirePermission permission="application:view">
      <div className="space-y-6">
        <PageHeader
          title="Intake"
          description="Everything pushed into the drop folder, and what happened to it. Files are matched to patients by the code in their path or file name."
        />

        <IntakeProgressPanel />

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {VIEWS.map((option) => {
            const count = getCount(counts.data, option.id)
            const active = option.id === view
            const borderClass = active
              ? 'border-[rgb(var(--primary))] shadow-sm'
              : 'border-[rgb(var(--border))] hover:border-[rgb(var(--foreground-muted))]'
            const needsAttention =
              count > 0 && (option.id === 'conflict' || option.id === 'failed')

            return (
              <button
                key={option.id}
                type="button"
                aria-pressed={active}
                onClick={() => changeView(option.id)}
                className={`rounded-lg border bg-[rgb(var(--surface))] p-4 text-left transition-colors ${borderClass}`}
              >
                <span className="block text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
                  {option.label}
                </span>
                <span className="mt-1 flex items-center gap-2">
                  <span className="text-2xl font-bold tabular-nums">{count}</span>
                  {needsAttention && <Badge tone={option.tone}>needs attention</Badge>}
                </span>
              </button>
            )
          })}
        </div>

        <Card className="p-5">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
            <div className="min-w-0">
              <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
                {current.label}
              </h2>
              <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
                {current.hint}
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <TextField
                label="Search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Path, code or reason..."
                aria-label="Search intake files"
              />
              {canCopy && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={visible.length === 0}
                  leadingIcon={<Copy className="size-3.5" aria-hidden="true" />}
                  onClick={() => void copyList()}
                  title="One line per file: full path, reason and detail"
                >
                  Copy list
                </Button>
              )}
              {canDownload && (
                <Button
                  variant="outline"
                  size="sm"
                  leadingIcon={<Download className="size-3.5" aria-hidden="true" />}
                  onClick={() => void downloadAll()}
                  title="Every file in this list as CSV, not just the ones shown"
                >
                  Download all (CSV)
                </Button>
              )}
            </div>
          </div>

          <DataTable
            data={visible}
            columns={columns}
            getRowId={(file) => file.id}
            isLoading={files.isLoading}
            isFetching={files.isFetching}
            error={files.error}
            loadingLabel="Loading intake files"
            emptyMessage={current.empty}
            rowActions={rowActions}
          />
          {total > loaded && (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-[rgb(var(--foreground-muted))]">
              <span>
                Showing the newest {loaded.toLocaleString()} of {total.toLocaleString()}
                {search ? ' (search only looks at the ones shown)' : ''}
              </span>
              {limit < 1000 && (
                <Button size="sm" variant="outline" onClick={() => setLimit(1000)}>
                  Show up to 1,000
                </Button>
              )}
            </div>
          )}
        </Card>
      </div>
    </RequirePermission>
  )
}
