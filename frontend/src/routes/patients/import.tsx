import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Download, Upload } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable, type Column } from '@/components/DataTable'
import { RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { usePatientImport } from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'
import { patientsApi } from '@/lib/api/resources'
import type { ImportResult, ImportRow } from '@/schemas/patient'

export const Route = createFileRoute('/patients/import')({
  component: () => (
    <RequirePermission permission="patient:create">
      <PatientImportPage />
    </RequirePermission>
  ),
})

const ACTION_LABELS: Record<ImportRow['action'], string> = {
  create: 'new',
  update: 'fill empty fields',
  unchanged: 'nothing new',
  error: 'skipped',
}

function actionTone(
  action: ImportRow['action']
): 'success' | 'info' | 'neutral' | 'danger' {
  if (action === 'create') return 'success'
  if (action === 'update') return 'info'
  if (action === 'error') return 'danger'
  return 'neutral'
}

const columns: Array<Column<ImportRow>> = [
  {
    id: 'line',
    header: 'Line',
    cell: (r) => <span className="tabular-nums">{r.line}</span>,
    sortValue: (r) => r.line,
  },
  {
    id: 'code',
    header: 'Patient code',
    cell: (r) => <span className="font-mono text-xs font-semibold">{r.code || '—'}</span>,
    sortValue: (r) => r.code,
  },
  {
    id: 'action',
    header: 'What happens',
    cell: (r) => <Badge tone={actionTone(r.action)}>{ACTION_LABELS[r.action]}</Badge>,
    sortValue: (r) => r.action,
  },
  {
    id: 'details',
    header: 'Details',
    cell: (r) => (
      <div className="space-y-1 text-xs">
        {r.errors.map((error) => (
          <p key={error} className="text-rose-600 dark:text-rose-400">
            {error}
          </p>
        ))}
        {r.filled.length > 0 ? <p>Sets: {r.filled.join(', ')}</p> : null}
        {r.conflicts.map((conflict) => (
          <p key={conflict} className="text-amber-700 dark:text-amber-400">
            Kept: {conflict}
          </p>
        ))}
      </div>
    ),
  },
]

function Counts({ result }: { result: ImportResult }) {
  const count = (key: string) => result.counts[key] ?? 0
  return (
    <div className="flex flex-wrap gap-2 text-sm">
      <Badge tone="success">{count('create')} new</Badge>
      <Badge tone="info">{count('update')} to fill in</Badge>
      <Badge tone="neutral">{count('unchanged')} nothing new</Badge>
      <Badge tone="danger">{count('error')} with problems</Badge>
    </div>
  )
}

function PatientImportPage() {
  useDocumentTitle('Import patients')
  const navigate = useNavigate()
  const importer = usePatientImport()
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [onlyProblems, setOnlyProblems] = useState(false)

  async function downloadTemplate() {
    try {
      const blob = await patientsApi.importTemplate()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'patients-template.csv'
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : 'Could not get the template'
      )
    }
  }

  function run(apply: boolean) {
    if (!file) return
    void importer
      .mutateAsync({ file, apply })
      .then(setResult)
      .catch(() => undefined)
  }

  const rows = result
    ? onlyProblems
      ? result.rows.filter((r) => r.action === 'error' || r.conflicts.length > 0)
      : result.rows
    : []
  const toApply = result ? (result.counts.create ?? 0) + (result.counts.update ?? 0) : 0

  return (
    <div className="space-y-6">
      <PageHeader
        title="Import patients"
        description="Load patients from an Excel or CSV file. New codes are created; patients already in the system only get their empty fields filled. Imported patients' details must be confirmed once before their first application is submitted."
        actions={
          <Button variant="outline" onClick={() => void navigate({ to: '/patients' })}>
            Back to patients
          </Button>
        }
      />

      <Card className="space-y-4 p-5">
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            leadingIcon={<Download className="size-4" aria-hidden="true" />}
            onClick={() => void downloadTemplate()}
          >
            Download template
          </Button>
          <span className="text-xs text-[rgb(var(--foreground-muted))]">
            Only “Patient code” is required. Dates as Excel dates or YYYY-MM-DD.
          </span>
        </div>

        <label className="block text-sm font-medium">
          File (.xlsx or .csv)
          <input
            type="file"
            accept=".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            className="mt-2 block w-full text-sm"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null)
              setResult(null)
            }}
          />
        </label>

        <div className="flex flex-wrap gap-3">
          <Button
            variant="outline"
            disabled={!file}
            isLoading={importer.isPending && !importer.variables?.apply}
            onClick={() => run(false)}
          >
            Preview
          </Button>
          <Button
            disabled={!file || !result || result.applied || toApply === 0}
            title={
              !result
                ? 'Preview first'
                : result.applied
                  ? 'Already imported'
                  : toApply === 0
                    ? 'Nothing to import'
                    : undefined
            }
            isLoading={importer.isPending && importer.variables?.apply}
            leadingIcon={<Upload className="size-4" aria-hidden="true" />}
            onClick={() => run(true)}
          >
            Import {toApply > 0 ? toApply : ''} patient{toApply === 1 ? '' : 's'}
          </Button>
        </div>
      </Card>

      {result ? (
        <Card className="space-y-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-2">
              <h2 className="text-sm font-bold">
                {result.applied ? 'Imported' : 'Preview: nothing has been changed yet'}
              </h2>
              <Counts result={result} />
              {result.ignored_columns.length > 0 ? (
                <p className="text-xs text-[rgb(var(--foreground-muted))]">
                  Columns not recognised, left out: {result.ignored_columns.join(', ')}
                </p>
              ) : null}
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={onlyProblems}
                onChange={(event) => setOnlyProblems(event.target.checked)}
              />
              Only problems and conflicts
            </label>
          </div>
          <DataTable
            data={rows}
            columns={columns}
            getRowId={(r) => String(r.line)}
            loadingLabel="Loading"
            emptyMessage="Nothing to show."
          />
        </Card>
      ) : null}
    </div>
  )
}
