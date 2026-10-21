import { createFileRoute } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileSpreadsheet, Search, Upload } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable, type Column } from '@/components/DataTable'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { SelectField, TextField } from '@/components/ui/Field'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { ApiError } from '@/lib/api/client'
import { redcapApi } from '@/lib/api/resources'
import { queryKeys } from '@/lib/queryKeys'
import {
  REDCAP_KIND_LABELS,
  REDCAP_KINDS,
  type FollowupSummary,
  type RedcapDataset,
  type RedcapImport,
  type RedcapKind,
} from '@/schemas/redcap'

export const Route = createFileRoute('/redcap/')({
  component: () => (
    <RequirePermission permission="redcap:view">
      <RedcapPage />
    </RequirePermission>
  ),
})

const titleClass = 'text-sm font-bold'
const mutedClass = 'text-xs text-[rgb(var(--foreground-muted))]'

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback
}

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

const DATASET_COLUMNS: Column<RedcapDataset>[] = [
  {
    id: 'dataset',
    header: 'Dataset',
    cell: (d) => <span className="font-mono">{d.dataset}</span>,
  },
  { id: 'fields', header: 'Fields', cell: (d) => d.fields.toLocaleString() },
  { id: 'patients', header: 'Patients', cell: (d) => d.patients.toLocaleString() },
  { id: 'values', header: 'Values', cell: (d) => d.values.toLocaleString() },
  { id: 'log', header: 'Log entries', cell: (d) => d.log_entries.toLocaleString() },
  {
    id: 'last',
    header: 'Last import',
    cell: (d) => (d.last_import ? d.last_import.slice(0, 16).replace('T', ' ') : '-'),
  },
]

function RedcapPage() {
  useDocumentTitle('REDCap')
  const status = useQuery({
    queryKey: queryKeys.redcap.status(),
    queryFn: () => redcapApi.status(),
  })
  const datasets = status.data?.datasets ?? []
  const simulated = status.data?.mode !== 'api'

  return (
    <div className="space-y-6">
      <PageHeader
        title="REDCap"
        description="Data exchanged with REDCap (protocol 9.1.12, 9.5): the data dictionary, records and audit log come in; follow-up lists and new patient codes go out. Files use REDCap's own export format, so the same code reads the REDCap API once it is connected."
      />

      <Card className="flex flex-wrap items-center gap-3 p-4 text-sm">
        <Badge tone={simulated ? 'warning' : 'success'}>
          {simulated ? 'Simulated: files' : 'Connected: REDCap API'}
        </Badge>
        <span className={mutedClass}>
          {simulated
            ? 'No REDCap API access yet. Import exported files here, or let scripts/redcap_sync.py read them nightly. Setting REDCAP_URL and a token per dataset switches the same sync to the API.'
            : 'The nightly sync reads REDCap directly. Files can still be imported here.'}
        </span>
      </Card>

      <Card className="space-y-3 p-5">
        <h2 className={titleClass}>Datasets in the app</h2>
        <DataTable
          data={datasets}
          columns={DATASET_COLUMNS}
          getRowId={(d) => d.dataset}
          isLoading={status.isLoading}
          isFetching={status.isFetching}
          error={status.error}
          loadingLabel="Loading REDCap datasets"
          emptyMessage="Nothing imported from REDCap yet."
        />
      </Card>

      <Can permission="redcap:import">
        <ImportCard datasets={datasets} />
      </Can>

      <Can permission="redcap:export">
        <FollowupCard />
        <NewRecordsCard datasets={datasets} />
      </Can>
    </div>
  )
}

function ImportCard({ datasets }: { datasets: RedcapDataset[] }) {
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<RedcapKind>('dictionary')
  const [dataset, setDataset] = useState(datasets[0]?.dataset ?? '')
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<RedcapImport | null>(null)
  const importer = useMutation({
    mutationFn: (apply: boolean) =>
      redcapApi.importFile(kind, dataset, file as File, apply),
    onError: (error) => toast.error(errorText(error, 'Could not read the file')),
  })

  function run(apply: boolean) {
    if (!file) return
    void importer
      .mutateAsync(apply)
      .then((next) => {
        setResult(next)
        if (apply) {
          toast.success(
            next.applied ? 'Imported from REDCap file' : 'Nothing new to import'
          )
          void queryClient.invalidateQueries({ queryKey: queryKeys.redcap.all })
          void queryClient.invalidateQueries({ queryKey: queryKeys.projects.all })
        }
      })
      .catch(() => undefined)
  }

  const reset = () => setResult(null)

  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className={titleClass}>Import a REDCap export</h2>
        <p className={mutedClass}>
          Import the data dictionary first: it decides which fields may go to Zone 2
          (coded, number and date fields; never identifier or free-text fields). The first
          column of a records file must be the record ID, which is the patient code.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <SelectField
          label="What"
          value={kind}
          onChange={(event) => {
            setKind(event.target.value as RedcapKind)
            reset()
          }}
          options={REDCAP_KINDS.map((value) => ({
            value,
            label: REDCAP_KIND_LABELS[value],
          }))}
        />
        <TextField
          label="Dataset (REDCap project)"
          placeholder="e.g. avsd_clinical"
          list="redcap-datasets"
          value={dataset}
          onChange={(event) => {
            setDataset(event.target.value.trim().toLowerCase())
            reset()
          }}
        />
        <datalist id="redcap-datasets">
          {datasets.map((d) => (
            <option key={d.dataset} value={d.dataset} />
          ))}
        </datalist>
        <label className="space-y-1 text-sm">
          <span className="font-medium">File (CSV or Excel)</span>
          <input
            type="file"
            accept=".csv,.xlsx,text/csv"
            className="block w-full text-sm"
            aria-label="REDCap export file"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null)
              reset()
            }}
          />
        </label>
      </div>
      <div className="flex flex-wrap gap-3">
        <Button
          variant="outline"
          disabled={!file || !dataset}
          isLoading={importer.isPending && importer.variables === false}
          leadingIcon={<Search className="size-4" aria-hidden="true" />}
          onClick={() => run(false)}
        >
          Preview
        </Button>
        <Button
          disabled={!file || !dataset || !result || result.applied}
          title={!result ? 'Preview first' : undefined}
          isLoading={importer.isPending && importer.variables === true}
          leadingIcon={<Upload className="size-4" aria-hidden="true" />}
          onClick={() => run(true)}
        >
          Import
        </Button>
      </div>
      {result ? (
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap gap-2">
            <Badge tone={result.applied ? 'success' : 'info'}>
              {result.applied ? 'imported' : 'preview'}
            </Badge>
            {Object.entries(result.counts).map(([key, value]) => (
              <Badge key={key} tone="neutral">
                {key.replace(/_/g, ' ')}: {value.toLocaleString()}
              </Badge>
            ))}
          </div>
          {result.notes.map((note) => (
            <p key={note} className={mutedClass}>
              {note}
            </p>
          ))}
          {result.problems.length > 0 ? (
            <ul className="space-y-1 text-xs text-rose-600 dark:text-rose-400">
              {result.problems.slice(0, 30).map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </Card>
  )
}

function FollowupCard() {
  const [version, setVersion] = useState('')
  const [days, setDays] = useState('365')
  const [summary, setSummary] = useState<FollowupSummary | null>(null)
  const recentDays = Math.max(1, Number(days) || 365)
  const check = useMutation({
    mutationFn: () => redcapApi.followup(version, recentDays),
    onSuccess: setSummary,
    onError: (error) => toast.error(errorText(error, 'Could not check follow-up')),
  })
  const download = useMutation({
    mutationFn: () => redcapApi.followupExport(version, recentDays),
    onSuccess: (blob) => save(blob, 'followup-list.xlsx'),
    onError: (error) => toast.error(errorText(error, 'Could not export the list')),
  })

  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className={titleClass}>Follow-up list (to REDCap)</h2>
        <p className={mutedClass}>
          Protocol 9.1.15: a patient gets an online follow-up when they are alive, have
          not withdrawn consent, signed the latest consent version, their site sent a
          recent follow-up, and they chose online follow-up. Everyone else goes to the
          manual list (9.1.14). The Excel has the automated, manual and not-contacted
          lists; the survey links are filled by REDCap once the API is connected.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <TextField
          label="Latest consent version"
          placeholder="e.g. v3 (empty: any granted)"
          value={version}
          onChange={(event) => {
            setVersion(event.target.value)
            setSummary(null)
          }}
        />
        <TextField
          label="Recent follow-up from the site (days)"
          type="number"
          min={1}
          value={days}
          onChange={(event) => {
            setDays(event.target.value)
            setSummary(null)
          }}
        />
      </div>
      <div className="flex flex-wrap gap-3">
        <Button
          variant="outline"
          isLoading={check.isPending}
          leadingIcon={<Search className="size-4" aria-hidden="true" />}
          onClick={() => check.mutate()}
        >
          Check
        </Button>
        <Button
          isLoading={download.isPending}
          leadingIcon={<FileSpreadsheet className="size-4" aria-hidden="true" />}
          onClick={() => download.mutate()}
        >
          Download list (Excel)
        </Button>
      </div>
      {summary ? (
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap gap-2">
            <Badge tone="success">{summary.automated} automated (online)</Badge>
            <Badge tone="warning">{summary.manual} manual</Badge>
            <Badge tone="neutral">{summary.not_contacted} not contacted</Badge>
          </div>
          {summary.sample.length > 0 ? (
            <ul className="space-y-1 text-xs">
              {summary.sample.map((row) => (
                <li key={row.patient_id}>
                  <span className="font-mono">{row.patient_id}</span>
                  {row.reasons.length
                    ? `: ${row.reasons.join('; ')}`
                    : `: online${row.consent_update ? ` (${row.consent_update})` : ''}`}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </Card>
  )
}

function NewRecordsCard({ datasets }: { datasets: RedcapDataset[] }) {
  const [dataset, setDataset] = useState(datasets[0]?.dataset ?? '')
  const download = useMutation({
    mutationFn: () => redcapApi.newRecordsExport(dataset),
    onSuccess: (blob) => save(blob, `new-records-${dataset}.csv`),
    onError: (error) => toast.error(errorText(error, 'Could not export the codes')),
  })

  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className={titleClass}>New patient codes (to REDCap)</h2>
        <p className={mutedClass}>
          Patients in the app with no record yet in a REDCap dataset, as a REDCap import
          file (record ID column only), so sites can enter data against a valid code
          (9.1.2).
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-64">
          <TextField
            label="Dataset"
            placeholder="e.g. avsd_clinical"
            list="redcap-datasets-export"
            value={dataset}
            onChange={(event) => setDataset(event.target.value.trim().toLowerCase())}
          />
          <datalist id="redcap-datasets-export">
            {datasets.map((d) => (
              <option key={d.dataset} value={d.dataset} />
            ))}
          </datalist>
        </div>
        <Button
          disabled={!dataset}
          isLoading={download.isPending}
          leadingIcon={<Download className="size-4" aria-hidden="true" />}
          onClick={() => download.mutate()}
        >
          Download CSV
        </Button>
      </div>
    </Card>
  )
}
