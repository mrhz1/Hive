import { createFileRoute } from '@tanstack/react-router'
import { FileDown, Lock, Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable, type Column } from '@/components/DataTable'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { SelectField, TextAreaField, TextField } from '@/components/ui/Field'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { usePermissions } from '@/hooks/useCurrentUser'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import {
  useCloseIncident,
  useCreateIncident,
  useIncidents,
  useLockApp,
  useLockdown,
  useMarkReportSent,
  useUpdateIncident,
} from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'
import { securityApi } from '@/lib/api/resources'
import {
  LEVELS,
  deadline,
  levelTone,
  type Incident,
  type Level,
} from '@/schemas/security'

export const Route = createFileRoute('/security/')({
  component: () => (
    <RequirePermission permission="security:view">
      <SecurityPage />
    </RequirePermission>
  ),
})

const LEVEL_OPTIONS = LEVELS.map((level) => ({ value: level, label: level }))

const titleClass =
  'text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase'

/** Now, as the value of a datetime-local input. */
function localNow(): string {
  const now = new Date()
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset())
  return now.toISOString().slice(0, 16)
}

function LockCard() {
  const lockdown = useLockdown()
  const lock = useLockApp()
  const [reason, setReason] = useState('')
  const [level, setLevel] = useState<Level>('critical')
  const locked = lockdown.data?.locked

  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className={titleClass}>Lock the app</h2>
        <p className="mt-1 text-sm text-[rgb(var(--foreground-muted))]">
          For a high or critical threat. Everyone without security management is stopped
          at once; the Program Manager, the application specialist and Host IT are
          emailed. Unlock from the banner at the top.
        </p>
      </div>
      {locked ? (
        <p className="text-sm font-semibold text-rose-600">The app is locked now.</p>
      ) : (
        <Can permission="security:manage">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_12rem_auto] md:items-end">
            <TextField
              label="Reason"
              value={reason}
              placeholder="e.g. a staff account is downloading identified files"
              onChange={(event) => setReason(event.target.value)}
            />
            <SelectField
              label="Level"
              value={level}
              options={LEVEL_OPTIONS}
              onChange={(event) => setLevel(event.target.value as Level)}
            />
            <Button
              variant="danger"
              disabled={!reason.trim()}
              isLoading={lock.isPending}
              leadingIcon={<Lock className="size-4" aria-hidden="true" />}
              onClick={() =>
                void lock
                  .mutateAsync({ reason: reason.trim(), level })
                  .then(() => setReason(''))
                  .catch(() => undefined)
              }
            >
              Lock now
            </Button>
          </div>
        </Can>
      )}
    </Card>
  )
}

function NewIncident({ onDone }: { onDone: () => void }) {
  const create = useCreateIncident()
  const [title, setTitle] = useState('')
  const [level, setLevel] = useState<Level>('high')
  const [detected, setDetected] = useState(localNow())
  const [description, setDescription] = useState('')

  return (
    <Card className="space-y-4 p-5">
      <h2 className={titleClass}>Record an incident</h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <TextField
          label="Title"
          required
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <SelectField
          label="Level"
          value={level}
          options={LEVEL_OPTIONS}
          onChange={(event) => setLevel(event.target.value as Level)}
        />
        <TextField
          label="Detected at"
          type="datetime-local"
          value={detected}
          hint="Local time; the 24 h and 72 h reports count from here"
          onChange={(event) => setDetected(event.target.value)}
        />
      </div>
      <TextAreaField
        label="What happened"
        rows={3}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
      />
      <div className="flex justify-end gap-3">
        <Button variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button
          disabled={!title.trim() || !detected}
          isLoading={create.isPending}
          onClick={() =>
            void create
              .mutateAsync({
                title: title.trim(),
                level,
                detected_at: new Date(detected).toISOString(),
                description: description.trim() || null,
              })
              .then(onDone)
              .catch(() => undefined)
          }
        >
          Record incident
        </Button>
      </div>
    </Card>
  )
}

const REPORT_FIELDS: Array<{ key: keyof Incident; label: string; hint: string }> = [
  { key: 'description', label: 'What happened', hint: '' },
  {
    key: 'data_affected',
    label: 'Data affected (scope)',
    hint: 'Which records, how many patients, identified or not',
  },
  { key: 'risk', label: 'Risk assessment', hint: 'Likelihood and impact of harm' },
  { key: 'containment', label: 'Containment actions', hint: 'What was done and when' },
  {
    key: 'affected_parties',
    label: 'Affected parties',
    hint: 'Patients, sites, others told',
  },
]

function IncidentDetail({ incident }: { incident: Incident }) {
  const { can } = usePermissions()
  const update = useUpdateIncident()
  const markSent = useMarkReportSent()
  const close = useCloseIncident()
  const editable = can('security:manage') && incident.status === 'open'
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(REPORT_FIELDS.map((f) => [f.key, String(incident[f.key] ?? '')]))
  )

  async function download() {
    try {
      const blob = await securityApi.report(incident.id)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `incident-${incident.id.slice(0, 8)}.docx`
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Could not get the report')
    }
  }

  const preliminary = deadline(incident.preliminary_due, incident.preliminary_sent_at)
  const full = deadline(incident.full_due, incident.full_sent_at)

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-bold">{incident.title}</h2>
          <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
            Detected {incident.detected_at.slice(0, 16).replace('T', ' ')} UTC ·{' '}
            {incident.status}
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          leadingIcon={<FileDown className="size-4" aria-hidden="true" />}
          onClick={() => void download()}
        >
          Report (.docx)
        </Button>
      </div>

      <div className="flex flex-wrap gap-4 text-sm">
        <div className="flex items-center gap-2">
          Preliminary report (24 h):{' '}
          <Badge tone={preliminary.tone}>{preliminary.text}</Badge>
          {editable && !incident.preliminary_sent_at ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => markSent.mutate({ id: incident.id, report: 'preliminary' })}
            >
              Mark sent
            </Button>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          Full report (72 h): <Badge tone={full.tone}>{full.text}</Badge>
          {editable && !incident.full_sent_at ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => markSent.mutate({ id: incident.id, report: 'full' })}
            >
              Mark sent
            </Button>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {REPORT_FIELDS.map((field) => (
          <TextAreaField
            key={field.key}
            label={field.label}
            hint={field.hint || undefined}
            rows={3}
            readOnly={!editable}
            value={values[field.key] ?? ''}
            onChange={(event) =>
              setValues((current) => ({ ...current, [field.key]: event.target.value }))
            }
          />
        ))}
      </div>

      {editable ? (
        <div className="flex justify-end gap-3">
          <Button
            variant="outline"
            isLoading={close.isPending}
            title="Needs the data affected, the containment and the full report sent"
            onClick={() => close.mutate(incident.id)}
          >
            Close incident
          </Button>
          <Button
            isLoading={update.isPending}
            onClick={() =>
              update.mutate({
                id: incident.id,
                values: Object.fromEntries(
                  REPORT_FIELDS.map((f) => [f.key, values[f.key]?.trim() || null])
                ),
              })
            }
          >
            Save
          </Button>
        </div>
      ) : null}
    </Card>
  )
}

function SecurityPage() {
  useDocumentTitle('Security')
  const incidents = useIncidents()
  const [creating, setCreating] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = incidents.data?.find((i) => i.id === selectedId)

  const columns: Array<Column<Incident>> = [
    {
      id: 'title',
      header: 'Incident',
      cell: (i) => <span className="font-semibold">{i.title}</span>,
      sortValue: (i) => i.title.toLowerCase(),
    },
    {
      id: 'level',
      header: 'Level',
      cell: (i) => <Badge tone={levelTone(i.level)}>{i.level}</Badge>,
      sortValue: (i) => LEVELS.indexOf(i.level as Level),
    },
    {
      id: 'detected',
      header: 'Detected (UTC)',
      cell: (i) => (
        <span className="text-xs tabular-nums">
          {i.detected_at.slice(0, 16).replace('T', ' ')}
        </span>
      ),
      sortValue: (i) => i.detected_at,
    },
    {
      id: 'reports',
      header: 'Reports',
      cell: (i) => {
        if (i.status === 'closed') return <Badge tone="success">closed</Badge>
        const preliminary = deadline(i.preliminary_due, i.preliminary_sent_at)
        const full = deadline(i.full_due, i.full_sent_at)
        return (
          <div className="flex flex-col gap-1 text-xs">
            <span>
              24 h: <Badge tone={preliminary.tone}>{preliminary.text}</Badge>
            </span>
            <span>
              72 h: <Badge tone={full.tone}>{full.text}</Badge>
            </span>
          </div>
        )
      },
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Security"
        description="Lock the app during an incident, and record incidents with their breach reports: preliminary within 24 hours, full within 72 hours."
        actions={
          creating ? null : (
            <Can permission="security:manage">
              <Button
                leadingIcon={<Plus className="size-4" aria-hidden="true" />}
                onClick={() => setCreating(true)}
              >
                Record incident
              </Button>
            </Can>
          )
        }
      />

      <LockCard />

      {creating ? <NewIncident onDone={() => setCreating(false)} /> : null}

      <DataTable
        data={incidents.data ?? []}
        columns={columns}
        getRowId={(i) => i.id}
        isLoading={incidents.isLoading}
        isFetching={incidents.isFetching}
        error={incidents.error}
        loadingLabel="Loading incidents"
        emptyMessage="No incidents recorded."
        rowActions={(i) => (
          <Button
            size="sm"
            variant={selectedId === i.id ? 'primary' : 'outline'}
            onClick={() => setSelectedId(selectedId === i.id ? null : i.id)}
          >
            {selectedId === i.id ? 'Hide' : 'Open'}
          </Button>
        )}
      />

      {selected ? <IncidentDetail key={selected.id} incident={selected} /> : null}
    </div>
  )
}
