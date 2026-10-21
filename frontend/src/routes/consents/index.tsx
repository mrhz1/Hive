import { createFileRoute } from '@tanstack/react-router'
import { Download, Plus, Upload } from 'lucide-react'
import { useState } from 'react'
import { DataTable, type Column } from '@/components/DataTable'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { SelectField, TextField } from '@/components/ui/Field'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useConsents, useRecordConsent } from '@/hooks/useResources'
import { consentsApi } from '@/lib/api/resources'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError } from '@/lib/api/client'
import {
  CONSENT_STATUSES,
  CONSENT_TYPE_LABELS,
  CONSENT_TYPES,
  consentTone,
  type Consent,
  type ConsentImportResult,
} from '@/schemas/project'

export const Route = createFileRoute('/consents/')({
  component: () => (
    <RequirePermission permission="consent:view">
      <ConsentPage />
    </RequirePermission>
  ),
})

const TEMPLATE = 'Patient code,Consent type,Status,Version,Consent date,Note\r\n'

function latestOnly(rows: Consent[]): Consent[] {
  const latest = new Map<string, Consent>()
  for (const row of rows) latest.set(`${row.patient_id}|${row.consent_type}`, row)
  return [...latest.values()]
}

const columns: Array<Column<Consent>> = [
  {
    id: 'code',
    header: 'Patient code',
    cell: (c) => <span className="font-mono text-xs font-semibold">{c.patient_id}</span>,
    sortValue: (c) => c.patient_id,
  },
  {
    id: 'type',
    header: 'Consent',
    cell: (c) => CONSENT_TYPE_LABELS[c.consent_type] ?? c.consent_type,
    sortValue: (c) => c.consent_type,
  },
  {
    id: 'status',
    header: 'Decision',
    cell: (c) => <Badge tone={consentTone(c.status)}>{c.status}</Badge>,
    sortValue: (c) => c.status,
  },
  {
    id: 'version',
    header: 'Form version',
    cell: (c) => c.version ?? '—',
  },
  {
    id: 'date',
    header: 'Consent date',
    cell: (c) => c.consent_date ?? '—',
    sortValue: (c) => c.consent_date ?? '',
  },
  {
    id: 'source',
    header: 'Recorded',
    cell: (c) => (
      <span className="text-xs text-[rgb(var(--foreground-muted))]">
        {(c.recorded_at ?? '').slice(0, 10)} · {c.source ?? ''}
        {c.note ? ` · ${c.note}` : ''}
      </span>
    ),
    sortValue: (c) => c.recorded_at ?? '',
  },
]

function ConsentPage() {
  useDocumentTitle('Consent matrix')
  const consents = useConsents()
  const [search, setSearch] = useState('')
  const [history, setHistory] = useState(false)

  const all = consents.data ?? []
  const term = search.trim().toUpperCase()
  const rows = (history ? all : latestOnly(all)).filter(
    (c) => !term || c.patient_id.includes(term)
  )

  return (
    <div className="space-y-6">
      <PageHeader
        title="Consent matrix"
        description="Each patient's consent decisions. A patient whose research consent is refused or withdrawn can't be in any project; for projects approved for PDFs and images, the same goes for the documents consent. The latest decision of each type counts; earlier ones are kept as history."
      />

      <Can permission="consent:update">
        <RecordCard />
        <ImportCard />
      </Can>

      <Card className="space-y-4 p-5">
        <div className="flex flex-wrap items-end gap-4">
          <div className="min-w-64 flex-1">
            <TextField
              label="Find a patient code"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="AA0001"
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={history}
              onChange={(event) => setHistory(event.target.checked)}
            />
            Show the full history
          </label>
        </div>
        <DataTable
          data={rows}
          columns={columns}
          getRowId={(c) => c.id}
          isLoading={consents.isLoading}
          isFetching={consents.isFetching}
          error={consents.error}
          loadingLabel="Loading consents"
          emptyMessage={
            term ? `No consent recorded for "${term}".` : 'No consent recorded yet.'
          }
        />
      </Card>
    </div>
  )
}

function RecordCard() {
  const record = useRecordConsent()
  const [code, setCode] = useState('')
  const [type, setType] = useState<string>('research')
  const [status, setStatus] = useState<string>('granted')
  const [version, setVersion] = useState('')
  const [day, setDay] = useState('')
  const [note, setNote] = useState('')

  return (
    <Card className="p-5">
      <h2 className="text-sm font-bold">Record a decision</h2>
      <form
        className="mt-4 grid gap-3 md:grid-cols-3"
        onSubmit={(event) => {
          event.preventDefault()
          void record
            .mutateAsync({
              patient_id: code,
              consent_type: type,
              status,
              version: version || null,
              consent_date: day || null,
              note: note || null,
            })
            .then(() => {
              setCode('')
              setVersion('')
              setDay('')
              setNote('')
            })
            .catch(() => undefined)
        }}
      >
        <TextField
          label="Patient code"
          placeholder="AA0001"
          required
          value={code}
          onChange={(event) => setCode(event.target.value)}
        />
        <SelectField
          label="Consent"
          value={type}
          onChange={(event) => setType(event.target.value)}
          options={CONSENT_TYPES.map((value) => ({
            value,
            label: CONSENT_TYPE_LABELS[value] ?? value,
          }))}
        />
        <SelectField
          label="Decision"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          options={CONSENT_STATUSES.map((value) => ({ value, label: value }))}
        />
        <TextField
          label="Form version"
          value={version}
          onChange={(event) => setVersion(event.target.value)}
        />
        <TextField
          label="Consent date"
          type="date"
          value={day}
          onChange={(event) => setDay(event.target.value)}
        />
        <TextField
          label="Note"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
        <div className="md:col-span-3">
          <Button
            type="submit"
            disabled={!code.trim()}
            isLoading={record.isPending}
            leadingIcon={<Plus className="size-4" aria-hidden="true" />}
          >
            Record
          </Button>
        </div>
      </form>
    </Card>
  )
}

function ImportCard() {
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<ConsentImportResult | null>(null)
  const importer = useMutation({
    mutationFn: (variables: { file: File; apply: boolean }) =>
      consentsApi.importFile(variables.file, variables.apply),
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Could not read the file')
    },
  })

  function run(apply: boolean) {
    if (!file) return
    void importer
      .mutateAsync({ file, apply })
      .then((next) => {
        setResult(next)
        if (apply) toast.success(`${next.counts.add ?? 0} decisions recorded`)
      })
      .catch(() => undefined)
  }

  function downloadTemplate() {
    const url = URL.createObjectURL(new Blob([TEMPLATE], { type: 'text/csv' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'consent-template.csv'
    link.click()
    URL.revokeObjectURL(url)
  }

  const toAdd = result?.counts.add ?? 0
  const problems = result?.rows.filter((r) => r.action === 'error') ?? []

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-bold">Import from a spreadsheet</h2>
          <p className="text-xs text-[rgb(var(--foreground-muted))]">
            Columns: Patient code, Consent type (research, documents or online_followup),
            Status (granted, refused or withdrawn), Version, Consent date, Note. Rows that
            match the latest decision are skipped.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          leadingIcon={<Download className="size-3.5" aria-hidden="true" />}
          onClick={downloadTemplate}
        >
          Template
        </Button>
      </div>
      <input
        type="file"
        accept=".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        className="block w-full text-sm"
        aria-label="Consent spreadsheet"
        onChange={(event) => {
          setFile(event.target.files?.[0] ?? null)
          setResult(null)
        }}
      />
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
          disabled={!file || !result || result.applied || toAdd === 0}
          title={!result ? 'Preview first' : undefined}
          isLoading={importer.isPending && importer.variables?.apply}
          leadingIcon={<Upload className="size-4" aria-hidden="true" />}
          onClick={() => run(true)}
        >
          Record {toAdd > 0 ? toAdd : ''} decision{toAdd === 1 ? '' : 's'}
        </Button>
      </div>
      {result ? (
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap gap-2">
            <Badge tone="success">
              {result.counts.add ?? 0} {result.applied ? 'recorded' : 'to record'}
            </Badge>
            <Badge tone="neutral">{result.counts.unchanged ?? 0} no change</Badge>
            <Badge tone="danger">{result.counts.error ?? 0} with problems</Badge>
          </div>
          {problems.length > 0 ? (
            <ul className="space-y-1 text-xs text-rose-600 dark:text-rose-400">
              {problems.slice(0, 50).map((row) => (
                <li key={row.line}>
                  Line {row.line} {row.code ? `(${row.code})` : ''}:{' '}
                  {row.errors.join('; ')}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </Card>
  )
}
