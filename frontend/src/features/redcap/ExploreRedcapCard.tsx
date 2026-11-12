import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Search, Upload } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { SelectField } from '@/components/ui/Field'
import { cn } from '@/lib/cn'
import { Badge, Card } from '@/components/ui/Misc'
import { ApiError } from '@/lib/api/client'
import { redcapApi } from '@/lib/api/resources'
import { queryKeys } from '@/lib/queryKeys'
import {
  REDCAP_KINDS,
  type RedcapKind,
  type RemoteInstrument,
  type RemotePreview,
} from '@/schemas/redcap'

const titleClass = 'text-sm font-bold'
const mutedClass = 'text-xs text-[rgb(var(--foreground-muted))]'
const cellClass = 'border-b border-[rgb(var(--border))] px-3 py-2 align-top'

const KIND_HELP: Record<RedcapKind, { title: string; text: string }> = {
  dictionary: {
    title: 'Data dictionary',
    text: 'The list of every field (name, type, choices). Always the whole project. Import it first: it decides which fields may go to Zone 2.',
  },
  records: {
    title: 'Records (patient data)',
    text: 'The values entered in REDCap, for the instruments you tick below.',
  },
  log: {
    title: 'Logging (audit trail)',
    text: 'Who changed what in REDCap. Only entries since the last import.',
  },
}

function Step({ number, title }: { number: number; title: string }) {
  return (
    <h3 className="flex items-center gap-2 text-sm font-semibold">
      <span className="flex size-6 items-center justify-center rounded-full bg-teal-600 text-xs text-white">
        {number}
      </span>
      {title}
    </h3>
  )
}

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback
}

export function ExploreRedcapCard({ canImport }: { canImport: boolean }) {
  const queryClient = useQueryClient()
  const remote = useQuery({
    queryKey: queryKeys.redcap.remote(),
    queryFn: () => redcapApi.remoteDatasets(),
  })
  const connected = (remote.data ?? []).filter((d) => d.connected)
  const [chosenDataset, setChosenDataset] = useState('')
  const dataset = chosenDataset || connected[0]?.dataset || ''
  const [kind, setKind] = useState<RedcapKind>('dictionary')
  // null = every instrument
  const [selected, setSelected] = useState<string[] | null>(null)
  const [result, setResult] = useState<RemotePreview | null>(null)

  const instruments = useQuery({
    queryKey: queryKeys.redcap.instruments(dataset),
    queryFn: () => redcapApi.remoteInstruments(dataset),
    enabled: Boolean(dataset),
  })
  const allNames = (instruments.data ?? []).map((i) => i.name)
  const chosen = selected ?? allNames

  const importer = useMutation({
    mutationFn: (apply: boolean) =>
      redcapApi.remoteImport(
        dataset,
        {
          kind,
          instruments: kind === 'records' ? chosen : [],
          ...(apply && result ? { fingerprint: result.fingerprint } : {}),
        },
        apply
      ),
    onError: (error) => toast.error(errorText(error, 'REDCap did not answer')),
  })

  function reset() {
    setResult(null)
  }

  function run(apply: boolean) {
    void importer
      .mutateAsync(apply)
      .then((next) => {
        setResult(next)
        if (apply) {
          toast.success(next.applied ? 'Imported from REDCap' : 'Nothing new to import')
          void queryClient.invalidateQueries({ queryKey: queryKeys.redcap.status() })
          void queryClient.invalidateQueries({ queryKey: queryKeys.projects.all })
        }
      })
      .catch(() => undefined)
  }

  function toggle(name: string) {
    const next = chosen.includes(name)
      ? chosen.filter((n) => n !== name)
      : [...chosen, name]
    setSelected(next)
    reset()
  }

  const project = remote.data?.find((d) => d.dataset === dataset)
  const needsInstruments = kind === 'records' && chosen.length === 0

  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className={titleClass}>Explore REDCap and import</h2>
        <p className={mutedClass}>
          Reads the connected REDCap project directly. Nothing is saved until you press
          Import, and the import saves exactly what you previewed.
        </p>
      </div>

      {remote.isLoading ? <p className={mutedClass}>Contacting REDCap…</p> : null}
      {remote.error ? (
        <p className="text-xs text-rose-600 dark:text-rose-400">
          {errorText(remote.error, 'Could not reach REDCap')}
        </p>
      ) : null}
      {(remote.data ?? [])
        .filter((d) => !d.connected)
        .map((d) => (
          <p key={d.dataset} className="text-xs text-rose-600 dark:text-rose-400">
            <span className="font-mono">{d.dataset}</span>: {d.error}
          </p>
        ))}

      {connected.length > 0 ? (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            <SelectField
              label="REDCap project"
              value={dataset}
              onChange={(event) => {
                setChosenDataset(event.target.value)
                setSelected(null)
                reset()
              }}
              options={connected.map((d) => ({
                value: d.dataset,
                label: `${d.title ?? d.dataset} (PID ${d.project_id ?? '?'})`,
              }))}
            />
            {project ? (
              <div className="flex flex-wrap items-end gap-2 pb-2">
                <Badge tone="success">connected</Badge>
                <Badge tone="neutral">dataset: {project.dataset}</Badge>
                {project.in_production ? (
                  <Badge tone="warning">production project</Badge>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="space-y-2">
            <Step number={1} title="What do you want to import?" />
            <div role="radiogroup" className="grid gap-2 md:grid-cols-3">
              {REDCAP_KINDS.map((value) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={kind === value}
                  onClick={() => {
                    setKind(value)
                    reset()
                  }}
                  className={cn(
                    'rounded-md border p-3 text-left transition-colors',
                    kind === value
                      ? 'border-teal-600 bg-teal-500/10'
                      : 'border-[rgb(var(--border))] hover:bg-teal-500/5'
                  )}
                >
                  <div className="text-sm font-semibold">{KIND_HELP[value].title}</div>
                  <div className={mutedClass}>{KIND_HELP[value].text}</div>
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <Step
              number={2}
              title={
                kind === 'records'
                  ? 'Tick the instruments to import'
                  : 'Explore the instruments (optional)'
              }
            />
            {kind !== 'records' ? (
              <p className={mutedClass}>
                {KIND_HELP[kind].title} covers the whole project. Open an instrument to
                see its fields; to import patient data of chosen instruments, pick Records
                in step 1.
              </p>
            ) : null}
            <InstrumentTable
              instruments={instruments.data ?? []}
              isLoading={instruments.isLoading}
              error={instruments.error}
              selectable={kind === 'records'}
              chosen={chosen}
              onToggle={toggle}
              onAll={(all) => {
                setSelected(all ? null : [])
                reset()
              }}
            />
          </div>

          <div className="space-y-2">
            <Step number={3} title="Preview, check, then import" />
            <p className={mutedClass}>
              Preview asks REDCap for the data and runs the import without saving: the
              counts show what would be saved, notes and problems show what would be
              skipped, and the table shows the first rows REDCap sent.
            </p>
            {canImport ? (
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  variant="outline"
                  disabled={!dataset || needsInstruments}
                  isLoading={importer.isPending && importer.variables === false}
                  leadingIcon={<Search className="size-4" aria-hidden="true" />}
                  onClick={() => run(false)}
                >
                  Preview {KIND_HELP[kind].title.toLowerCase()}
                </Button>
                <Button
                  disabled={!result || result.applied || needsInstruments}
                  title={!result ? 'Preview first' : undefined}
                  isLoading={importer.isPending && importer.variables === true}
                  leadingIcon={<Upload className="size-4" aria-hidden="true" />}
                  onClick={() => run(true)}
                >
                  Import
                </Button>
                {needsInstruments ? (
                  <span className={mutedClass}>Tick at least one instrument</span>
                ) : null}
              </div>
            ) : (
              <p className={mutedClass}>
                You can explore REDCap; importing needs the redcap:import permission.
              </p>
            )}
          </div>

          {result ? <PreviewResult result={result} /> : null}
        </>
      ) : null}
    </Card>
  )
}

function InstrumentTable({
  instruments,
  isLoading,
  error,
  selectable,
  chosen,
  onToggle,
  onAll,
}: {
  instruments: RemoteInstrument[]
  isLoading: boolean
  error: unknown
  selectable: boolean
  chosen: string[]
  onToggle: (name: string) => void
  onAll: (all: boolean) => void
}) {
  if (isLoading) return <p className={mutedClass}>Loading instruments…</p>
  if (error)
    return (
      <p className="text-xs text-rose-600 dark:text-rose-400">
        {errorText(error, 'Could not load the instruments')}
      </p>
    )
  if (!instruments.length) return null
  return (
    <InstrumentRows
      instruments={instruments}
      selectable={selectable}
      chosen={chosen}
      onToggle={onToggle}
      onAll={onAll}
    />
  )
}

function InstrumentRows({
  instruments,
  selectable,
  chosen,
  onToggle,
  onAll,
}: {
  instruments: RemoteInstrument[]
  selectable: boolean
  chosen: string[]
  onToggle: (name: string) => void
  onAll: (all: boolean) => void
}) {
  const [open, setOpen] = useState<string | null>(null)
  const total = instruments.reduce((sum, i) => sum + i.fields, 0)

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={mutedClass}>
          {instruments.length} instruments, {total.toLocaleString()} fields.
          {selectable ? ` ${chosen.length} ticked for import.` : ''}
        </p>
        {selectable ? (
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" onClick={() => onAll(true)}>
              Select all
            </Button>
            <Button size="sm" variant="ghost" onClick={() => onAll(false)}>
              Select none
            </Button>
          </div>
        ) : null}
      </div>
      <div className="max-h-96 overflow-auto rounded-md border border-[rgb(var(--border))]">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-[rgb(var(--background))]">
            <tr>
              {selectable ? <th className={cellClass} aria-label="Import" /> : null}
              <th className={cellClass}>Instrument</th>
              <th className={cellClass} aria-label="Fields list" />
              <th className={cellClass}>Fields</th>
              <th
                className={cellClass}
                title="Identifier, date and free-text fields. REDCap leaves these out when your export rights are De-identified."
              >
                Left out if De-identified
              </th>
            </tr>
          </thead>
          <tbody>
            {instruments.map((i) => {
              const removed = i.identifiers + i.dates + i.free_text
              const isOpen = open === i.name
              return [
                <tr key={i.name}>
                  {selectable ? (
                    <td className={cellClass}>
                      <input
                        type="checkbox"
                        className="size-4 cursor-pointer accent-teal-600"
                        aria-label={`Import ${i.label}`}
                        checked={chosen.includes(i.name)}
                        onChange={() => onToggle(i.name)}
                      />
                    </td>
                  ) : null}
                  <td className={cellClass}>
                    <div className="font-medium">{i.label}</div>
                    <div className="font-mono text-[11px] opacity-70">{i.name}</div>
                  </td>
                  <td className={cellClass}>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-expanded={isOpen}
                      leadingIcon={
                        isOpen ? (
                          <ChevronDown className="size-3.5" aria-hidden="true" />
                        ) : (
                          <ChevronRight className="size-3.5" aria-hidden="true" />
                        )
                      }
                      onClick={() => setOpen(isOpen ? null : i.name)}
                    >
                      Fields
                    </Button>
                  </td>
                  <td className={cellClass}>{i.fields}</td>
                  <td
                    className={cellClass}
                    title={`${i.identifiers} identifiers, ${i.dates} dates, ${i.free_text} free text`}
                  >
                    {removed || '-'}
                  </td>
                </tr>,
                isOpen ? (
                  <tr key={`${i.name}-fields`}>
                    <td colSpan={selectable ? 5 : 4} className={cellClass}>
                      <FieldList instrument={i} />
                    </td>
                  </tr>
                ) : null,
              ]
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const LEFT_OUT_LABEL: Record<string, string> = {
  identifier: 'identifier',
  date: 'date',
  free_text: 'free text',
}

function FieldList({ instrument }: { instrument: RemoteInstrument }) {
  return (
    <div className="max-h-72 overflow-auto">
      <table className="w-full text-left text-[11px]">
        <thead>
          <tr>
            <th className={cellClass}>Field</th>
            <th className={cellClass}>Label</th>
            <th className={cellClass}>Type</th>
            <th className={cellClass}>If De-identified</th>
          </tr>
        </thead>
        <tbody>
          {instrument.field_list.map((f) => (
            <tr key={f.name}>
              <td className={cn(cellClass, 'font-mono')}>{f.name}</td>
              <td className={cellClass}>{f.label}</td>
              <td className={cellClass}>{f.type}</td>
              <td className={cellClass}>
                {f.left_out ? (
                  <Badge tone="warning">
                    left out: {LEFT_OUT_LABEL[f.left_out] ?? f.left_out}
                  </Badge>
                ) : (
                  'kept'
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PreviewResult({ result }: { result: RemotePreview }) {
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap gap-2">
        <Badge tone={result.applied ? 'success' : 'info'}>
          {result.applied ? 'imported' : 'preview: nothing saved yet'}
        </Badge>
        <Badge tone="neutral">
          rows from REDCap: {result.rows_in_export.toLocaleString()}
        </Badge>
        {Object.entries(result.counts).map(([key, value]) => (
          <Badge key={key} tone="neutral">
            {key.replace(/_/g, ' ')}: {value.toLocaleString()}
          </Badge>
        ))}
      </div>
      {result.instruments.length ? (
        <p className={mutedClass}>Instruments: {result.instruments.join(', ')}</p>
      ) : null}
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
      {result.sample_columns.length ? (
        <div className="space-y-1">
          <p className={mutedClass}>
            First {result.sample_rows.length} rows and {result.sample_columns.length}{' '}
            columns of what REDCap sent:
          </p>
          <div className="overflow-auto rounded-md border border-[rgb(var(--border))]">
            <table className="w-full text-left font-mono text-[11px]">
              <thead>
                <tr>
                  {result.sample_columns.map((column, index) => (
                    <th key={`${column}-${index}`} className={cellClass}>
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.sample_rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((value, index) => (
                      <td key={index} className={cellClass}>
                        {value}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  )
}
