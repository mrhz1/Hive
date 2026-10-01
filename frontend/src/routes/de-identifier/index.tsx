import { createFileRoute } from '@tanstack/react-router'
import { Copy, Download, GitCompareArrows, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable, type Column } from '@/components/DataTable'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { SelectField, TextField } from '@/components/ui/Field'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { IntakeProgressPanel } from '@/features/intake/IntakeProgressPanel'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import {
  useIntakeFileCodes,
  useIntakeFiles,
  useIntakeStatus,
  useResolveIntakeConflict,
  useRetryAllIntakeFiles,
  useRetryIntakeFile,
} from '@/hooks/useResources'
import { intakeApi } from '@/lib/api/resources'
import { formatFileSize } from '@/schemas/applicationFile'
import {
  NO_CODE,
  codeFormatExample,
  filesToText,
  problemSearchText,
  type ProblemFile,
  type IntakeStatus,
  type ProblemList,
} from '@/schemas/intake'

/** Which patient codes the de-identifier picks up, as set in the server's .env. */
function AcceptedCodes({ status }: { status: IntakeStatus }) {
  const formats = status.code_formats

  return (
    <Card className="flex flex-wrap items-center gap-x-3 gap-y-2 p-4 text-sm">
      <span className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
        Accepted patient codes
      </span>
      {formats.length > 0 ? (
        formats.map((format) => (
          <Badge key={`${format.prefix}:${format.digits}`} tone="info">
            <span className="font-mono">
              {format.prefix} + {format.digits} digits
            </span>
            <span className="ml-1.5 font-mono opacity-70">
              e.g. {codeFormatExample(format)}
            </span>
          </Badge>
        ))
      ) : status.code_pattern_is_default ? (
        <span className="text-[rgb(var(--foreground-muted))]">
          Any 2 to 4 letters followed by 3 or 4 digits, e.g. AA0001
        </span>
      ) : (
        <span className="font-mono text-xs">{status.code_pattern}</span>
      )}
      <span className="text-xs text-[rgb(var(--foreground-muted))]">
        Files with any other code are excluded.
      </span>
    </Card>
  )
}

export const Route = createFileRoute('/de-identifier/')({
  component: IntakePage,
})

const PAGE_SIZE = 500
const CONFLICT_REASON = 'path and file name disagree'

const VIEWS: { id: ProblemList; label: string; hint: string; empty: string }[] = [
  {
    id: 'failed',
    label: 'Failed',
    hint: 'Redaction did not work for these files. Retry moves a file back to the incoming folder for the next run.',
    empty: 'Nothing has failed.',
  },
  {
    id: 'attention',
    label: 'Excluded',
    hint: 'Left out of de-identification: no patient code, an unsupported format, a duplicate, or the path and file name have different codes. Pick a code to see what was excluded for that patient. Fix these at the source and push them again, or pick the right code for a conflict.',
    empty: 'Nothing was excluded.',
  },
]

function IntakePage() {
  useDocumentTitle('De-Identifier')

  const { data: status } = useIntakeStatus()
  const [view, setView] = useState<ProblemList>('failed')
  const [limit, setLimit] = useState(PAGE_SIZE)
  const [search, setSearch] = useState('')
  const [code, setCode] = useState('')
  const files = useIntakeFiles(view, limit, code)
  const codes = useIntakeFileCodes(view)
  const resolve = useResolveIntakeConflict()
  const retry = useRetryIntakeFile()
  const retryAll = useRetryAllIntakeFiles()

  const current = VIEWS.find((v) => v.id === view) ?? VIEWS[0]!

  const allRows = files.data?.rows ?? []
  const searchText = search.trim().toLowerCase()
  const visible = searchText
    ? allRows.filter((file) => problemSearchText(file).includes(searchText))
    : allRows

  function changeView(newView: ProblemList) {
    setView(newView)
    setSearch('')
    setCode('')
    setLimit(PAGE_SIZE)
  }

  function getCount(id: ProblemList) {
    if (!status) return 0
    return id === 'failed' ? status.failed : status.needs_attention
  }

  async function downloadAll() {
    try {
      const blob = await intakeApi.exportCsv(view, code || undefined)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = code ? `intake-${view}-${code}.csv` : `intake-${view}.csv`
      document.body.append(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
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

  const columns: Array<Column<ProblemFile>> = [
    {
      id: 'path',
      header: 'File',
      cell: (file) => (
        <div className="min-w-0">
          <span className="block truncate font-semibold">{file.file_name}</span>
          <span
            className="block truncate font-mono text-xs text-[rgb(var(--foreground-muted))]"
            title={file.full_path}
          >
            {file.full_path}
          </span>
        </div>
      ),
      sortValue: (file) => file.full_path,
    },
    {
      id: 'code',
      header: 'Code',
      cell: (file) => {
        if (file.path_code && file.name_code && file.path_code !== file.name_code) {
          return (
            <span className="font-mono text-xs">
              path <strong>{file.path_code}</strong> · name{' '}
              <strong>{file.name_code}</strong>
            </span>
          )
        }
        const code = file.path_code || file.name_code
        if (code) return <span className="font-mono text-sm font-bold">{code}</span>
        return <span className="text-xs text-[rgb(var(--foreground-muted))]">none</span>
      },
      sortValue: (file) => file.path_code ?? file.name_code ?? '',
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
    {
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

  function rowActions(file: ProblemFile) {
    if (view === 'failed') {
      return (
        <Can permission="deidentifier:run">
          <Button
            size="sm"
            variant="outline"
            aria-label={`Retry ${file.file_name}`}
            isLoading={retry.isPending && retry.variables === file.path}
            leadingIcon={<RotateCcw className="size-3.5" aria-hidden="true" />}
            onClick={() => retry.mutate(file.path)}
          >
            Retry
          </Button>
        </Can>
      )
    }

    if (file.reason !== CONFLICT_REASON) return null

    const choices = []
    if (file.path_code) choices.push({ code: file.path_code, source: 'path' })
    if (file.name_code) choices.push({ code: file.name_code, source: 'name' })

    return (
      <Can permission="deidentifier:run">
        {choices.map((choice) => (
          <Button
            key={choice.code}
            size="sm"
            variant="outline"
            aria-label={`File ${file.file_name} under ${choice.code}`}
            isLoading={
              resolve.isPending &&
              resolve.variables?.path === file.path &&
              resolve.variables.code === choice.code
            }
            leadingIcon={<GitCompareArrows className="size-3.5" aria-hidden="true" />}
            onClick={() => resolve.mutate({ path: file.path, code: choice.code })}
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

  const total = files.data?.total ?? 0
  const loaded = allRows.length

  return (
    <RequirePermission permission="deidentifier:view">
      <div className="space-y-6">
        <PageHeader
          title="De-Identifier"
          description="Files in the incoming folder are de-identified when you click Start. Each done file is filed on its patient's draft application, creating the patient and the draft when needed. Anything that failed or was excluded is listed below."
        />

        {status ? <AcceptedCodes status={status} /> : null}

        <IntakeProgressPanel />

        <div className="grid grid-cols-2 gap-3">
          {VIEWS.map((option) => {
            const count = getCount(option.id)
            const active = option.id === view
            const borderClass = active
              ? 'border-[rgb(var(--primary))] shadow-sm'
              : 'border-[rgb(var(--border))] hover:border-[rgb(var(--foreground-muted))]'

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
                  {count > 0 && (
                    <Badge tone={option.id === 'failed' ? 'danger' : 'warning'}>
                      {option.id === 'failed' ? 'needs a retry' : 'excluded'}
                    </Badge>
                  )}
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
              <div className="w-48">
                <SelectField
                  label="Patient code"
                  aria-label="Filter by patient code"
                  value={code}
                  onChange={(e) => {
                    setCode(e.target.value)
                    setLimit(PAGE_SIZE)
                  }}
                  placeholder={`All codes${codes.data ? ` (${codes.data.length})` : ''}`}
                  options={(codes.data ?? []).map((c) => ({
                    value: c.code,
                    label: `${c.code === NO_CODE ? 'No code' : c.code} (${c.files})`,
                  }))}
                />
              </div>
              <TextField
                label="Search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Path, code or reason..."
                aria-label="Search intake files"
              />
              {view === 'failed' ? (
                <Can permission="deidentifier:run">
                  <Button
                    size="sm"
                    disabled={total === 0}
                    isLoading={retryAll.isPending}
                    leadingIcon={<RotateCcw className="size-3.5" aria-hidden="true" />}
                    title={
                      code
                        ? `Move every failed file for ${code === NO_CODE ? 'no code' : code} back to the incoming folder`
                        : 'Move every failed file back to the incoming folder, not just the ones shown'
                    }
                    onClick={() => {
                      const scope = code
                        ? ` for ${code === NO_CODE ? 'no code' : code}`
                        : ''
                      if (
                        window.confirm(
                          `Move all ${total.toLocaleString()} failed file${total === 1 ? '' : 's'}${scope} back to the incoming folder? They will be done in the next run.`
                        )
                      )
                        retryAll.mutate(code || undefined)
                    }}
                  >
                    Retry all{total ? ` (${total.toLocaleString()})` : ''}
                  </Button>
                </Can>
              ) : null}
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
              <Button
                variant="outline"
                size="sm"
                leadingIcon={<Download className="size-3.5" aria-hidden="true" />}
                onClick={() => void downloadAll()}
                title={
                  code
                    ? `Every file in this list for ${code === NO_CODE ? 'no code' : code}, as CSV`
                    : 'Every file in this list as CSV, not just the ones shown'
                }
              >
                Download all (CSV)
              </Button>
            </div>
          </div>

          <DataTable
            data={visible}
            columns={columns}
            getRowId={(file) => file.path}
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
                Showing {loaded.toLocaleString()} of {total.toLocaleString()}
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
