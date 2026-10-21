import { createFileRoute, useNavigate } from '@tanstack/react-router'
import {
  Archive,
  CalendarPlus,
  FolderSync,
  PackageCheck,
  Save,
  Search,
  Trash2,
  UserMinus,
  UserPlus,
  Users,
} from 'lucide-react'
import { useState } from 'react'
import { ConfirmDeleteModal } from '@/components/ConfirmDeleteModal'
import { DataTable, type Column } from '@/components/DataTable'
import { ForbiddenPage, NotFoundPage } from '@/components/ErrorPages'
import { ReasonDialog } from '@/components/ReasonDialog'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import {
  CheckboxField,
  SelectField,
  TextAreaField,
  TextField,
} from '@/components/ui/Field'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { usePermissions } from '@/hooks/useCurrentUser'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import {
  useAddProjectMember,
  useBuildWorkspace,
  useCohortSearch,
  useDeleteProject,
  useDeleteWorkspace,
  useEndProject,
  useExtendWorkspace,
  usePrepareProject,
  useProject,
  useProjectCandidates,
  useRemoveProjectMember,
  useSetCohort,
  useUpdateProject,
  useUserDirectory,
} from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'
import { daysLeft } from '@/schemas/abstraction'
import {
  PROJECT_STATUS_LABELS,
  groupByPrefix,
  projectTone,
  releaseTone,
  type CohortCriteria,
  type CohortSearchResult,
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
  if (query.error instanceof ApiError && query.error.isPermissionDenied) {
    return <ForbiddenPage requiredPermission="membership of this project" />
  }
  if (!query.data) return <NotFoundPage />

  const project = query.data
  const ended = project.status === 'ended'
  const locked = project.status === 'in_review' || ended

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
        {project.status === 'in_review' ? (
          <span className="text-sm text-[rgb(var(--foreground-muted))]">
            A safe copy is waiting in the Zone 2 inbox. The project can be changed once it
            is approved or sent back.
          </span>
        ) : null}
      </div>

      {ended ? (
        <Card className="p-4 text-sm">
          <strong>This project has ended</strong>
          {project.status_reason ? ` (${project.status_reason})` : ''}
          {project.updated_at ? `, ${project.updated_at.slice(0, 10)}` : ''}. Nothing more
          can be released. Its Zone 2 copy and archive are kept; remove the researchers'
          access in Users and Roles.
        </Card>
      ) : null}

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
      <MembersCard project={project} />
      <CohortCard project={project} locked={locked} />
      <WorkspaceCard project={project} />
      <ReleaseCard project={project} />
      <EndCard project={project} />
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
          description="Required to prepare. Patients whose consent is refused or withdrawn in the consent matrix are always kept out; this confirms consent was checked for the others."
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
  const candidates = useProjectCandidates(project.id)
  const save = useSetCohort(project.id)
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(project.cohort.map((m) => m.patient_id))
  )
  const [search, setSearch] = useState('')

  const text = search.trim().toUpperCase()
  const all = candidates.data ?? []
  const blocked = new Map(
    all
      .filter((c) => c.excluded_reason)
      .map((c) => [c.patient_id, c.excluded_reason ?? ''])
  )
  const shown = text ? all.filter((c) => c.patient_id.includes(text)) : all
  const shownCodes = shown.map((c) => c.patient_id).filter((code) => !blocked.has(code))
  const allShown = shownCodes.length > 0 && shownCodes.every((code) => selected.has(code))
  const cohorts = groupByPrefix(
    all.map((c) => c.patient_id).filter((code) => !blocked.has(code))
  )
  const blockedSelected = [...selected].filter((code) => blocked.has(code))

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
      {cohorts.length > 1 ? (
        <div className="space-y-2">
          <p className="text-sm font-medium">By cohort (code prefix)</p>
          <div className="flex flex-wrap gap-2">
            {cohorts.map(([prefix, codes]) => {
              const picked = codes.filter((code) => selected.has(code)).length
              const all = picked === codes.length
              return (
                <Button
                  key={prefix}
                  size="sm"
                  variant={all ? 'primary' : 'outline'}
                  title={
                    all ? `Remove all ${prefix} patients` : `Add all ${prefix} patients`
                  }
                  onClick={() => toggle(codes, !all)}
                >
                  <span className="font-mono">{prefix}</span>
                  <span className="tabular-nums">
                    {picked > 0 && !all ? `${picked}/` : ''}
                    {codes.length}
                  </span>
                </Button>
              )
            })}
          </div>
        </div>
      ) : null}

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
          disabled={shownCodes.length === 0}
          onClick={() => toggle(shownCodes, !allShown)}
        >
          {allShown ? 'Clear shown' : `Select all shown (${shownCodes.length})`}
        </Button>
      </div>

      <CriteriaSearch
        projectId={project.id}
        onAdd={(codes) => toggle(codes, true)}
        onReplace={(codes) => setSelected(new Set(codes))}
      />

      {blockedSelected.length > 0 ? (
        <Card className="border-rose-500/40 p-3 text-sm">
          {blockedSelected.length} chosen patient
          {blockedSelected.length === 1 ? ' is' : 's are'} kept out by the consent matrix
          and must be removed before saving: {blockedSelected.join(', ')}.{' '}
          <button
            type="button"
            className="font-semibold underline"
            onClick={() => toggle(blockedSelected, false)}
          >
            Remove them
          </button>
        </Card>
      ) : null}

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
                <label
                  className={`flex items-center gap-3 px-3 py-2 text-sm ${
                    c.excluded_reason
                      ? 'cursor-not-allowed opacity-70'
                      : 'cursor-pointer hover:bg-[rgb(var(--background-secondary))]'
                  }`}
                >
                  <input
                    type="checkbox"
                    className="size-4 accent-teal-600"
                    checked={selected.has(c.patient_id)}
                    disabled={Boolean(c.excluded_reason) && !selected.has(c.patient_id)}
                    onChange={(event) => toggle([c.patient_id], event.target.checked)}
                  />
                  <span className="w-28 font-mono font-semibold">{c.patient_id}</span>
                  <span className="text-xs text-[rgb(var(--foreground-muted))]">
                    {c.applications} submitted application
                    {c.applications === 1 ? '' : 's'} · {c.documents} document
                    {c.documents === 1 ? '' : 's'}
                  </span>
                  {c.excluded_reason ? (
                    <Badge tone="danger">{c.excluded_reason}</Badge>
                  ) : null}
                </label>
              </li>
            ))
          )}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button
          isLoading={save.isPending}
          disabled={blockedSelected.length > 0}
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

function splitList(value: string): string[] {
  return value
    .split(/[\s,;]+/)
    .map((part) => part.trim())
    .filter(Boolean)
}

const EMPTY_CRITERIA = {
  prefixes: '',
  registered_from: '',
  registered_to: '',
  age_min: '',
  age_max: '',
  countries: '',
  states: '',
  institution_codes: '',
  alive_only: false,
  modalities: '',
  document_from: '',
  document_to: '',
  exclude_codes: '',
}

function toCriteria(form: typeof EMPTY_CRITERIA): CohortCriteria {
  const number = (value: string) => (value.trim() === '' ? null : Number(value))
  const day = (value: string) => value || null
  return {
    prefixes: splitList(form.prefixes),
    registered_from: day(form.registered_from),
    registered_to: day(form.registered_to),
    age_min: number(form.age_min),
    age_max: number(form.age_max),
    countries: form.countries
      .split(/[,;]+/)
      .map((part) => part.trim())
      .filter(Boolean),
    states: splitList(form.states),
    institution_codes: splitList(form.institution_codes),
    alive_only: form.alive_only,
    modalities: splitList(form.modalities),
    document_from: day(form.document_from),
    document_to: day(form.document_to),
    exclude_codes: splitList(form.exclude_codes),
  }
}

function CriteriaSearch({
  projectId,
  onAdd,
  onReplace,
}: {
  projectId: string
  onAdd: (codes: string[]) => void
  onReplace: (codes: string[]) => void
}) {
  const search = useCohortSearch(projectId)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_CRITERIA)
  const [result, setResult] = useState<CohortSearchResult | null>(null)

  const field =
    (name: keyof typeof EMPTY_CRITERIA) => (event: { target: { value: string } }) =>
      setForm((current) => ({ ...current, [name]: event.target.value }))

  if (!open) {
    return (
      <Button
        size="sm"
        variant="outline"
        leadingIcon={<Search className="size-3.5" aria-hidden="true" />}
        onClick={() => setOpen(true)}
      >
        Find by criteria
      </Button>
    )
  }

  const excluded = Object.entries(result?.excluded ?? {})

  return (
    <div className="space-y-3 rounded-lg border border-[rgb(var(--border))] p-4">
      <div>
        <p className="text-sm font-medium">Find by inclusion / exclusion criteria</p>
        <p className="text-xs text-[rgb(var(--foreground-muted))]">
          Every filter you fill in must match; empty ones are ignored. Lists can be
          separated by commas. Patients the consent matrix keeps out are never matched.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <TextField
          label="Cohort (code prefixes)"
          placeholder="AA, BB"
          value={form.prefixes}
          onChange={field('prefixes')}
        />
        <TextField
          label="Registered from"
          type="date"
          value={form.registered_from}
          onChange={field('registered_from')}
        />
        <TextField
          label="Registered to"
          type="date"
          value={form.registered_to}
          onChange={field('registered_to')}
        />
        <TextField
          label="Age at registration, from"
          type="number"
          min={0}
          value={form.age_min}
          onChange={field('age_min')}
        />
        <TextField
          label="Age at registration, to"
          type="number"
          min={0}
          value={form.age_max}
          onChange={field('age_max')}
        />
        <TextField
          label="Institution codes"
          value={form.institution_codes}
          onChange={field('institution_codes')}
        />
        <TextField
          label="Countries"
          placeholder="Canada, US"
          value={form.countries}
          onChange={field('countries')}
        />
        <TextField
          label="States / provinces"
          placeholder="ON, QC"
          value={form.states}
          onChange={field('states')}
        />
        <TextField
          label="Has documents of type or modality"
          placeholder="ECHO_REPORT, MR"
          value={form.modalities}
          onChange={field('modalities')}
        />
        <TextField
          label="Document dated from"
          type="date"
          value={form.document_from}
          onChange={field('document_from')}
        />
        <TextField
          label="Document dated to"
          type="date"
          value={form.document_to}
          onChange={field('document_to')}
        />
        <TextField
          label="Exclude these codes"
          placeholder="AA0001, AA0002"
          value={form.exclude_codes}
          onChange={field('exclude_codes')}
        />
        <CheckboxField
          label="Living patients only"
          description="Leave out patients with a date of death."
          checked={form.alive_only}
          onChange={(event) =>
            setForm((current) => ({ ...current, alive_only: event.target.checked }))
          }
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          isLoading={search.isPending}
          leadingIcon={<Search className="size-3.5" aria-hidden="true" />}
          onClick={() =>
            void search
              .mutateAsync(toCriteria(form))
              .then(setResult)
              .catch(() => undefined)
          }
        >
          Find
        </Button>
        <Button size="sm" variant="outline" onClick={() => setForm(EMPTY_CRITERIA)}>
          Clear
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Close
        </Button>
      </div>
      {result ? (
        <div className="space-y-2 text-sm">
          <p>
            <strong>{result.matches.length}</strong> patient
            {result.matches.length === 1 ? '' : 's'} match.
            {excluded.length > 0
              ? ` ${excluded.length} more matched but the consent matrix keeps them out.`
              : ''}
          </p>
          {excluded.length > 0 ? (
            <ul className="text-xs text-[rgb(var(--foreground-muted))]">
              {excluded.slice(0, 20).map(([code, why]) => (
                <li key={code}>
                  <span className="font-mono">{code}</span>: {why}
                </li>
              ))}
            </ul>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={result.matches.length === 0}
              onClick={() => onAdd(result.matches)}
            >
              Add matches to the selection
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={result.matches.length === 0}
              onClick={() => onReplace(result.matches)}
            >
              Select only the matches
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function MembersCard({ project }: { project: ProjectDetail }) {
  const { can } = usePermissions()
  const manage = can('project:manage')
  const add = useAddProjectMember(project.id)
  const remove = useRemoveProjectMember(project.id)
  const { data: people = [] } = useUserDirectory(manage)
  const [picked, setPicked] = useState('')
  const ended = project.status === 'ended'
  const members = new Set(project.members.map((m) => m.user_id))

  return (
    <Card className="p-5">
      <h2 className={titleClass}>Members</h2>
      <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
        Only members can open this project and its workspace. Add the people approved for
        it.
      </p>

      <ul className="mt-3 divide-y divide-[rgb(var(--border))] text-sm">
        {project.members.map((member) => (
          <li key={member.id} className="flex items-center justify-between gap-3 py-2">
            <span className="flex items-center gap-2">
              <Users
                className="size-4 text-[rgb(var(--foreground-muted))]"
                aria-hidden="true"
              />
              {member.username ?? member.user_id}
            </span>
            {manage ? (
              <Button
                variant="ghost"
                size="sm"
                isLoading={remove.isPending && remove.variables === member.user_id}
                leadingIcon={<UserMinus className="size-3.5" aria-hidden="true" />}
                onClick={() => remove.mutate(member.user_id)}
              >
                Remove
              </Button>
            ) : null}
          </li>
        ))}
        {project.members.length === 0 ? (
          <li className="py-2 text-[rgb(var(--foreground-muted))]">No members yet.</li>
        ) : null}
      </ul>

      {manage && !ended ? (
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <div className="min-w-60 flex-1">
            <SelectField
              label="Add a member"
              value={picked}
              placeholder="Pick a person"
              options={people
                .filter((person) => person.is_active && !members.has(person.id))
                .map((person) => ({
                  value: person.id,
                  label: `${person.first_name} ${person.last_name} (${person.username})`,
                }))}
              onChange={(event) => setPicked(event.target.value)}
            />
          </div>
          <Button
            disabled={!picked}
            isLoading={add.isPending}
            leadingIcon={<UserPlus className="size-4" aria-hidden="true" />}
            onClick={() =>
              void add
                .mutateAsync(picked)
                .then(() => setPicked(''))
                .catch(() => undefined)
            }
          >
            Add
          </Button>
        </div>
      ) : null}
    </Card>
  )
}

function WorkspaceCard({ project }: { project: ProjectDetail }) {
  const { can } = usePermissions()
  const build = useBuildWorkspace(project.id)
  const extend = useExtendWorkspace(project.id)
  const remove = useDeleteWorkspace(project.id)
  const [includeDocuments, setIncludeDocuments] = useState(true)
  const [dialog, setDialog] = useState<'extend' | 'delete' | null>(null)
  const ended = project.status === 'ended'
  const built = Boolean(project.workspace_path)
  const manage = can('project:workspace')
  const expires = (project.workspace_expires_at ?? '').slice(0, 10)
  const left = daysLeft(project.workspace_expires_at)

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <h2 className={titleClass}>Workspace (Zone 1X)</h2>
          <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
            The cohort's tables, cleaned by the standard cleanup rules, and their
            de-identified PDFs and images, in the project's own folder for data cleanup.
            CHSS codes stay here; nothing in it goes to Zone 2. It is deleted 90 days
            after it is built unless extended. Release archives are not affected.
          </p>
        </div>
        {built ? (
          <Badge tone={left !== null && left <= 14 ? 'warning' : 'success'}>
            {left !== null && left <= 0 ? 'expired' : `deleted on ${expires}`}
          </Badge>
        ) : (
          <Badge tone="neutral">not built</Badge>
        )}
      </div>

      {built ? (
        <dl className="mt-4 grid gap-2 text-sm md:grid-cols-2">
          <div>
            <dt className="text-xs text-[rgb(var(--foreground-muted))]">Folder</dt>
            <dd className="font-mono text-[11px] break-all">{project.workspace_path}</dd>
          </div>
          <div>
            <dt className="text-xs text-[rgb(var(--foreground-muted))]">Last built</dt>
            <dd>{(project.workspace_built_at ?? '').slice(0, 16).replace('T', ' ')}</dd>
          </div>
        </dl>
      ) : null}

      {manage ? (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <CheckboxField
            label="Copy the PDFs and images"
            checked={includeDocuments}
            onChange={(event) => setIncludeDocuments(event.target.checked)}
          />
          <Button
            size="sm"
            disabled={ended || project.cohort.length === 0}
            title={
              ended
                ? 'The project has ended'
                : project.cohort.length === 0
                  ? 'Choose the patients first'
                  : undefined
            }
            isLoading={build.isPending}
            leadingIcon={<FolderSync className="size-3.5" aria-hidden="true" />}
            onClick={() => build.mutate(includeDocuments)}
          >
            {built ? 'Rebuild workspace' : 'Build workspace'}
          </Button>
          {built ? (
            <>
              <Button
                size="sm"
                variant="outline"
                leadingIcon={<CalendarPlus className="size-3.5" aria-hidden="true" />}
                onClick={() => setDialog('extend')}
              >
                Extend 90 days
              </Button>
              <Button
                size="sm"
                variant="danger"
                leadingIcon={<Trash2 className="size-3.5" aria-hidden="true" />}
                onClick={() => setDialog('delete')}
              >
                Delete workspace
              </Button>
            </>
          ) : null}
        </div>
      ) : null}

      {dialog === 'extend' ? (
        <ReasonDialog
          title="Keep the workspace 90 more days?"
          description="Extending needs an approval. Record which one; it goes in the audit log."
          confirmLabel="Extend"
          placeholder="e.g. REB amendment 4, approved by the CHSS manager"
          isBusy={extend.isPending}
          onCancel={() => setDialog(null)}
          onConfirm={(reason) =>
            void extend
              .mutateAsync(reason)
              .then(() => setDialog(null))
              .catch(() => undefined)
          }
        />
      ) : null}
      {dialog === 'delete' ? (
        <ReasonDialog
          title="Delete the workspace now?"
          description="Its tables and copied documents are removed. It can be built again from the cohort. Release archives stay."
          confirmLabel="Delete workspace"
          placeholder="e.g. data cleanup done, moved to Zone 2"
          isBusy={remove.isPending}
          onCancel={() => setDialog(null)}
          onConfirm={(reason) =>
            void remove
              .mutateAsync(reason)
              .then(() => setDialog(null))
              .catch(() => undefined)
          }
        />
      ) : null}
    </Card>
  )
}

function ReleaseCard({ project }: { project: ProjectDetail }) {
  const prepare = usePrepareProject(project.id)

  const missing: string[] = []
  if (!project.approval_reference) missing.push('an approval reference')
  if (!project.consent_confirmed) missing.push('consent confirmed')
  if (project.cohort.length === 0) missing.push('at least one patient')
  const waiting = project.status === 'in_review'
  const ended = project.status === 'ended'

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
            disabled={waiting || ended || missing.length > 0}
            title={
              ended
                ? 'The project has ended'
                : waiting
                  ? 'A release is already waiting for review'
                  : missing.length
                    ? `Needs ${missing.join(', ')}`
                    : undefined
            }
            isLoading={prepare.isPending}
            leadingIcon={<PackageCheck className="size-4" aria-hidden="true" />}
            onClick={() => prepare.mutate()}
          >
            {waiting ? 'Waiting for review in the Zone 2 inbox' : 'Prepare safe copy'}
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

function EndCard({ project }: { project: ProjectDetail }) {
  const end = useEndProject(project.id)
  const [confirming, setConfirming] = useState(false)
  if (project.status === 'ended' || project.releases.length === 0) return null
  const waiting = project.status === 'in_review'

  return (
    <Can permission="project:update">
      <div>
        <Button
          variant="outline"
          size="sm"
          disabled={waiting}
          title={waiting ? 'Approve or send back the waiting release first' : undefined}
          leadingIcon={<Archive className="size-3.5" aria-hidden="true" />}
          onClick={() => setConfirming(true)}
        >
          End project
        </Button>
        {confirming ? (
          <ReasonDialog
            title={`End ${project.name}?`}
            description="No more safe copies can be prepared. The Zone 2 copy and the archive stay as they are. Remove the researchers' access yourself in Users and Roles."
            confirmLabel="End project"
            placeholder="e.g. study closed, results published"
            isBusy={end.isPending}
            onCancel={() => setConfirming(false)}
            onConfirm={(reason) =>
              void end
                .mutateAsync(reason)
                .then(() => setConfirming(false))
                .catch(() => undefined)
            }
          />
        ) : null}
      </div>
    </Can>
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
