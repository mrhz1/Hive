import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { PackageCheck, Save, Trash2, Users } from 'lucide-react'
import { useState } from 'react'
import { ConfirmDeleteModal } from '@/components/ConfirmDeleteModal'
import { DataTable, type Column } from '@/components/DataTable'
import { NotFoundPage } from '@/components/ErrorPages'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { CheckboxField, TextAreaField, TextField } from '@/components/ui/Field'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { usePermissions } from '@/hooks/useCurrentUser'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import {
  useDeleteProject,
  usePrepareProject,
  useProject,
  useProjectCandidates,
  useSetCohort,
  useUpdateProject,
} from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'
import {
  PROJECT_STATUS_LABELS,
  projectTone,
  releaseTone,
  type ProjectDetail,
  type Release,
} from '@/schemas/project'

export const Route = createFileRoute('/projects/$projectId')({
  component: () => (
    <RequirePermission permission="project:view">
      <ProjectPage />
    </RequirePermission>
  ),
})

const titleClass =
  'text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase'

function ProjectPage() {
  const { projectId } = Route.useParams()
  const query = useProject(projectId)
  useDocumentTitle(query.data ? query.data.name : 'Project')

  if (query.isLoading) return <LoadingBlock label="Loading project" />
  if (query.error instanceof ApiError && query.error.isNotFound) return <NotFoundPage />
  if (!query.data) return <NotFoundPage />

  const project = query.data
  const locked = project.status === 'in_review'

  return (
    <div className="space-y-6">
      <PageHeader
        title={project.name}
        description={`Project ${project.short_code}. Pick the patients, record the approval and consent, then prepare the safe copy for review.`}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={projectTone(project.status)}>
          {PROJECT_STATUS_LABELS[project.status] ?? project.status}
        </Badge>
        {locked ? (
          <span className="text-sm text-[rgb(var(--foreground-muted))]">
            A safe copy is waiting in the Zone 2 inbox. The project can be changed once it
            is approved or sent back.
          </span>
        ) : null}
      </div>

      {project.status === 'rejected' && project.status_reason ? (
        <Card className="border-rose-500/40 p-4 text-sm">
          <strong>Sent back by the reviewer:</strong> {project.status_reason}. Fix it and
          prepare the safe copy again.
        </Card>
      ) : null}

      <DetailsCard
        key={`${project.id}:${project.updated_at}`}
        project={project}
        locked={locked}
      />
      <CohortCard project={project} locked={locked} />
      <ReleaseCard project={project} />
      <DeleteCard project={project} />
    </div>
  )
}

function DetailsCard({ project, locked }: { project: ProjectDetail; locked: boolean }) {
  const { can } = usePermissions()
  const update = useUpdateProject(project.id)
  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description ?? '')
  const [approval, setApproval] = useState(project.approval_reference ?? '')
  const [consent, setConsent] = useState(project.consent_confirmed)
  const [documents, setDocuments] = useState(project.documents_approved)
  const readOnly = locked || !can('project:update')

  return (
    <Card className="p-5">
      <h2 className={titleClass}>Project and approvals</h2>
      <form
        className="mt-4 grid gap-4 md:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault()
          update.mutate({
            name: name.trim() || project.name,
            description,
            approval_reference: approval,
            consent_confirmed: consent,
            documents_approved: documents,
          })
        }}
      >
        <TextField
          label="Name"
          value={name}
          disabled={readOnly}
          onChange={(event) => setName(event.target.value)}
        />
        <TextField
          label="Approval reference"
          hint="The ethics / data access approval this project runs under. Required to prepare."
          value={approval}
          disabled={readOnly}
          placeholder="e.g. REB-2026-17"
          onChange={(event) => setApproval(event.target.value)}
        />
        <div className="md:col-span-2">
          <TextAreaField
            label="Description"
            value={description}
            disabled={readOnly}
            rows={3}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
        <CheckboxField
          label="Patient consent confirmed"
          description="Required to prepare. Confirms consent was checked for every patient in the project."
          checked={consent}
          disabled={readOnly}
          onChange={(event) => setConsent(event.target.checked)}
        />
        <CheckboxField
          label="Approved for documents (PDFs and images)"
          description="Only for projects with a demonstrated need, such as machine learning. Without it the safe copy lists the documents but does not include the files."
          checked={documents}
          disabled={readOnly}
          onChange={(event) => setDocuments(event.target.checked)}
        />
        {readOnly ? null : (
          <div className="md:col-span-2">
            <Button
              type="submit"
              isLoading={update.isPending}
              leadingIcon={<Save className="size-4" aria-hidden="true" />}
            >
              Save
            </Button>
          </div>
        )}
      </form>
    </Card>
  )
}

function CohortCard({ project, locked }: { project: ProjectDetail; locked: boolean }) {
  const { can } = usePermissions()
  const [editing, setEditing] = useState(false)

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className={titleClass}>Patients ({project.cohort.length})</h2>
          <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
            Each patient gets a project-only ID and a random date shift, kept here and
            never released.
          </p>
        </div>
        {!locked && can('project:update') && !editing ? (
          <Button
            size="sm"
            variant="outline"
            leadingIcon={<Users className="size-3.5" aria-hidden="true" />}
            onClick={() => setEditing(true)}
          >
            Choose patients
          </Button>
        ) : null}
      </div>

      {editing ? (
        <CohortPicker project={project} onDone={() => setEditing(false)} />
      ) : (
        <div className="mt-4">
          <DataTable
            data={project.cohort}
            columns={[
              {
                id: 'code',
                header: 'Patient code',
                cell: (m) => (
                  <span className="font-mono text-xs font-semibold">{m.patient_id}</span>
                ),
                sortValue: (m) => m.patient_id,
              },
              {
                id: 'pid',
                header: 'Project ID',
                cell: (m) => (
                  <span className="font-mono text-xs">{m.project_patient_id}</span>
                ),
                sortValue: (m) => m.project_patient_id,
              },
              {
                id: 'apps',
                header: 'Submitted applications',
                isNumeric: true,
                cell: (m) => m.applications,
                sortValue: (m) => m.applications,
              },
              {
                id: 'docs',
                header: 'Documents',
                isNumeric: true,
                cell: (m) => m.documents,
                sortValue: (m) => m.documents,
              },
            ]}
            getRowId={(m) => m.patient_id}
            isLoading={false}
            isFetching={false}
            error={null}
            loadingLabel="Loading patients"
            emptyMessage="No patients yet. Choose the patients this project needs."
          />
        </div>
      )}
    </Card>
  )
}

function CohortPicker({
  project,
  onDone,
}: {
  project: ProjectDetail
  onDone: () => void
}) {
  const candidates = useProjectCandidates()
  const save = useSetCohort(project.id)
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(project.cohort.map((m) => m.patient_id))
  )
  const [search, setSearch] = useState('')

  const text = search.trim().toUpperCase()
  const all = candidates.data ?? []
  const shown = text ? all.filter((c) => c.patient_id.includes(text)) : all
  const allShown = shown.length > 0 && shown.every((c) => selected.has(c.patient_id))

  const toggle = (codes: string[], on: boolean) =>
    setSelected((current) => {
      const next = new Set(current)
      for (const code of codes) {
        if (on) next.add(code)
        else next.delete(code)
      }
      return next
    })

  return (
    <div className="mt-4 space-y-3">
      <p className="text-xs text-[rgb(var(--foreground-muted))]">
        Patients with at least one submitted application. Only submitted applications go
        into the safe copy.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-64 flex-1">
          <TextField
            label="Find a patient code"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="AA0001"
          />
        </div>
        <Button
          size="sm"
          variant="outline"
          disabled={shown.length === 0}
          onClick={() =>
            toggle(
              shown.map((c) => c.patient_id),
              !allShown
            )
          }
        >
          {allShown ? 'Clear shown' : `Select all shown (${shown.length})`}
        </Button>
      </div>

      {candidates.isLoading ? (
        <LoadingBlock label="Loading patients" />
      ) : (
        <ul
          className="max-h-96 divide-y divide-[rgb(var(--border))] overflow-y-auto rounded-lg border border-[rgb(var(--border))]"
          aria-label="Patients that can be in the project"
        >
          {shown.length === 0 ? (
            <li className="p-3 text-sm text-[rgb(var(--foreground-muted))]">
              {all.length === 0
                ? 'No patient has a submitted application yet.'
                : 'No code matches.'}
            </li>
          ) : (
            shown.map((c) => (
              <li key={c.patient_id}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-[rgb(var(--background-secondary))]">
                  <input
                    type="checkbox"
                    className="size-4 accent-teal-600"
                    checked={selected.has(c.patient_id)}
                    onChange={(event) => toggle([c.patient_id], event.target.checked)}
                  />
                  <span className="w-28 font-mono font-semibold">{c.patient_id}</span>
                  <span className="text-xs text-[rgb(var(--foreground-muted))]">
                    {c.applications} submitted application
                    {c.applications === 1 ? '' : 's'} · {c.documents} document
                    {c.documents === 1 ? '' : 's'}
                  </span>
                </label>
              </li>
            ))
          )}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button
          isLoading={save.isPending}
          onClick={() =>
            void save
              .mutateAsync([...selected])
              .then(onDone)
              .catch(() => undefined)
          }
        >
          Save patients ({selected.size})
        </Button>
        <Button variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

function ReleaseCard({ project }: { project: ProjectDetail }) {
  const prepare = usePrepareProject(project.id)

  const missing: string[] = []
  if (!project.approval_reference) missing.push('an approval reference')
  if (!project.consent_confirmed) missing.push('consent confirmed')
  if (project.cohort.length === 0) missing.push('at least one patient')
  const waiting = project.status === 'in_review'

  const columns: Array<Column<Release>> = [
    {
      id: 'release',
      header: 'Release',
      cell: (r) => <span className="font-mono text-xs">{r.id}</span>,
      sortValue: (r) => r.id,
    },
    {
      id: 'status',
      header: 'Status',
      cell: (r) => (
        <div className="min-w-0">
          <Badge tone={releaseTone(r.status)}>
            {r.status === 'in_review' ? 'waiting for review' : r.status}
          </Badge>
          {r.status_reason ? (
            <span className="mt-1 block text-xs text-[rgb(var(--foreground-muted))]">
              {r.status_reason}
            </span>
          ) : null}
        </div>
      ),
      sortValue: (r) => r.status,
    },
    {
      id: 'counts',
      header: 'Contents',
      cell: (r) => (
        <span className="text-sm">
          {r.patients} patients · {r.applications} applications · {r.documents} documents
          {r.files_included ? ' (files included)' : ''}
        </span>
      ),
    },
    {
      id: 'where',
      header: 'Released to',
      cell: (r) => (
        <span className="font-mono text-[11px] break-all text-[rgb(var(--foreground-muted))]">
          {r.release_path ?? '—'}
        </span>
      ),
    },
    {
      id: 'prepared',
      header: 'Prepared',
      cell: (r) => (
        <span className="text-sm">
          {(r.prepared_at ?? '').slice(0, 16).replace('T', ' ')}
        </span>
      ),
      sortValue: (r) => r.prepared_at ?? '',
    },
  ]

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className={titleClass}>Safe copy (Zone 2)</h2>
          <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
            Preparing makes the safe copy (project IDs, shifted dates, no identifiers or
            free text) and an archive with the original and the ID map. The safe copy then
            waits in the Zone 2 inbox for the CHSS manager.
          </p>
        </div>
        <Can permission="zone2:prepare">
          <Button
            disabled={waiting || missing.length > 0}
            title={
              waiting
                ? 'A release is already waiting for review'
                : missing.length
                  ? `Needs ${missing.join(', ')}`
                  : undefined
            }
            isLoading={prepare.isPending}
            leadingIcon={<PackageCheck className="size-4" aria-hidden="true" />}
            onClick={() => prepare.mutate()}
          >
            Prepare safe copy
          </Button>
        </Can>
      </div>
      {missing.length > 0 && !waiting ? (
        <p className="mt-3 text-sm text-[rgb(var(--foreground-muted))]">
          Before preparing, the project needs {missing.join(', ')}.
        </p>
      ) : null}
      <div className="mt-4">
        <DataTable
          data={project.releases}
          columns={columns}
          getRowId={(r) => r.id}
          isLoading={false}
          isFetching={false}
          error={null}
          loadingLabel="Loading releases"
          emptyMessage="Nothing prepared yet."
        />
      </div>
    </Card>
  )
}

function DeleteCard({ project }: { project: ProjectDetail }) {
  const navigate = useNavigate()
  const remove = useDeleteProject()
  const [confirming, setConfirming] = useState(false)
  if (project.releases.length > 0) return null

  return (
    <Can permission="project:delete">
      <div>
        <Button
          variant="danger"
          size="sm"
          leadingIcon={<Trash2 className="size-3.5" aria-hidden="true" />}
          onClick={() => setConfirming(true)}
        >
          Delete project
        </Button>
        <ConfirmDeleteModal
          open={confirming}
          entityLabel="Project"
          targetName={project.name}
          isDeleting={remove.isPending}
          onCancel={() => setConfirming(false)}
          onConfirm={() =>
            void remove
              .mutateAsync(project.id)
              .then(() => navigate({ to: '/projects' }))
              .catch(() => undefined)
          }
        />
      </div>
    </Can>
  )
}
