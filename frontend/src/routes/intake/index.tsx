import { createFileRoute } from '@tanstack/react-router'
import { Copy, Download, GitCompareArrows, RotateCcw } from 'lucide-react'
import { useMemo, useState } from 'react'
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
  intakeHaystack,
  refusalReport,
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
}

const CONFLICT_VIEW: ViewOption = {
  id: 'conflict',
  label: 'Conflicts',
  hint: 'The path and the file name name different patients. Choose which is right.',
  tone: 'danger',
}

const VIEWS: ViewOption[] = [
  CONFLICT_VIEW,
  {
    id: 'skipped',
    label: 'Skipped',
    hint: 'No patient code, or a format we cannot redact. Fix these at source and push them again.',
    tone: 'warning',
  },
  {
    id: 'failed',
    label: 'Failed',
    hint: 'Redaction was attempted and did not work. The reason is on each row -- retry it here, or push a corrected file to the same place.',
    tone: 'danger',
  },
  {
    id: 'queued',
    label: 'Waiting',
    hint: 'Placed under a code and waiting for a worker.',
    tone: 'info',
  },
  {
    id: 'done',
    label: 'De-identified',
    hint: 'Redacted into the de_identified mirror, ready to be picked for an application.',
    tone: 'success',
  },
]

function count(counts: IntakeCounts | undefined, view: View): number {
  if (!counts) return 0
  return view === 'queued' ? counts.queued + counts.processing : counts[view]
}

function IntakePage() {
  useDocumentTitle('Intake')

  const counts = useIntakeCounts()
  const [view, setView] = useState<View>('conflict')
  // A page at a time: a hundred thousand skipped files in one response is a
  // browser that stops responding. "Show more" raises the limit.
  const PAGE = 500
  const [shown, setShown] = useState(PAGE)
  const files = useIntakePage(view, shown)
  const resolve = useResolveIntakeConflict()
  const retry = useRetryIntakeFile()
  const [search, setSearch] = useState('')

  const current = VIEWS.find((v) => v.id === view) ?? CONFLICT_VIEW

  const visible = useMemo(() => {
    const rows = files.data?.rows ?? []
    const term = search.trim().toLowerCase()
    if (!term) return rows
    return rows.filter((file) => intakeHaystack(file).includes(term))
  }, [files.data, search])

  async function downloadAll() {
    try {
      const blob = await intakeApi.exportCsv(view)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `intake-${view}.csv`
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch {
      toast.error('Could not download the list')
    }
  }

  async function copyList() {
    try {
      await navigator.clipboard.writeText(refusalReport(visible))
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
      cell: (file) =>
        file.patient_code ? (
          <span className="font-mono text-sm font-bold">{file.patient_code}</span>
        ) : view === 'conflict' ? (
          <span className="font-mono text-xs">
            path <strong>{file.path_code}</strong> · name{' '}
            <strong>{file.name_code}</strong>
          </span>
        ) : (
          <span className="text-xs text-[rgb(var(--foreground-muted))]">none</span>
        ),
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
              {file.reason ? <span className="font-semibold">{file.reason}</span> : null}
              {file.detail ? (
                <span className="block text-xs text-[rgb(var(--foreground-muted))]">
                  {file.detail}
                </span>
              ) : null}
            </div>
          ),
          sortValue: (file) => file.reason ?? '',
        },
  ]

  return (
    <RequirePermission permission="application:view">
      <div className="space-y-6">
        <PageHeader
          title="Intake"
          description="Everything pushed into the drop folder, and what happened to it. Nothing here needs an application -- files are placed by the patient code in their path or name."
        />

        <IntakeProgressPanel />

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {VIEWS.map((option) => {
            const n = count(counts.data, option.id)
            const active = option.id === view
            return (
              <button
                key={option.id}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  setView(option.id)
                  setSearch('')
                  setShown(PAGE)
                }}
                className={
                  'rounded-lg border p-4 text-left transition-colors ' +
                  (active
                    ? 'border-[rgb(var(--primary))] bg-[rgb(var(--surface))] shadow-sm'
                    : 'border-[rgb(var(--border))] bg-[rgb(var(--surface))] hover:border-[rgb(var(--foreground-muted))]')
                }
              >
                <span className="block text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
                  {option.label}
                </span>
                <span className="mt-1 flex items-center gap-2">
                  <span className="text-2xl font-bold tabular-nums">{n}</span>
                  {n > 0 && (option.id === 'conflict' || option.id === 'failed') ? (
                    <Badge tone={option.tone}>needs attention</Badge>
                  ) : null}
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
              {view === 'skipped' || view === 'failed' ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={visible.length === 0}
                  leadingIcon={<Copy className="size-3.5" aria-hidden="true" />}
                  onClick={() => void copyList()}
                  title="One line per file: full path, reason, detail -- for whoever owns the source"
                >
                  Copy list
                </Button>
              ) : null}
              {view === 'skipped' || view === 'failed' || view === 'conflict' ? (
                <Button
                  variant="outline"
                  size="sm"
                  leadingIcon={<Download className="size-3.5" aria-hidden="true" />}
                  onClick={() => void downloadAll()}
                  title="Every file in this list as CSV -- not just the ones shown"
                >
                  Download all (CSV)
                </Button>
              ) : null}
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
            emptyMessage={
              view === 'conflict'
                ? 'No conflicts.'
                : view === 'skipped'
                  ? 'Nothing was skipped.'
                  : view === 'failed'
                    ? 'Nothing has failed.'
                    : 'Nothing here.'
            }
            rowActions={
              view === 'conflict'
                ? (file) => (
                    <Can permission="application:update">
                      {[file.path_code, file.name_code]
                        .filter((code): code is string => Boolean(code))
                        .map((code, index) => (
                          <Button
                            key={code}
                            size="sm"
                            variant="outline"
                            aria-label={`File ${file.file_name} under ${code}`}
                            isLoading={
                              resolve.isPending &&
                              resolve.variables?.fileId === file.id &&
                              resolve.variables.code === code
                            }
                            leadingIcon={
                              <GitCompareArrows className="size-3.5" aria-hidden="true" />
                            }
                            onClick={() => resolve.mutate({ fileId: file.id, code })}
                          >
                            {code}
                            <span className="ml-1 text-[10px] font-normal opacity-70">
                              {index === 0 ? 'path' : 'name'}
                            </span>
                          </Button>
                        ))}
                    </Can>
                  )
                : view === 'failed'
                  ? (file) => (
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
                  : undefined
            }
          />
          {files.data && files.data.total > (files.data.rows.length ?? 0) ? (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-[rgb(var(--foreground-muted))]">
              <span>
                Showing the newest {files.data.rows.length.toLocaleString()} of{' '}
                {files.data.total.toLocaleString()}
                {search ? ' -- search looks only at the ones shown' : ''}
              </span>
              {shown < 1000 ? (
                <Button size="sm" variant="outline" onClick={() => setShown(1000)}>
                  Show up to 1,000
                </Button>
              ) : null}
            </div>
          ) : null}
        </Card>
      </div>
    </RequirePermission>
  )
}
