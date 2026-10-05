import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { DataTable, type Column } from '@/components/DataTable'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/Field'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useCreateProject, useProjects } from '@/hooks/useResources'
import { PROJECT_STATUS_LABELS, projectTone, type Project } from '@/schemas/project'

export const Route = createFileRoute('/projects/')({
  component: () => (
    <RequirePermission permission="project:view">
      <ProjectsPage />
    </RequirePermission>
  ),
})

function shortDate(value: string | null | undefined) {
  return value ? value.slice(0, 10) : '—'
}

function ProjectsPage() {
  useDocumentTitle('Projects')
  const navigate = useNavigate()
  const { data, isLoading, isFetching, error } = useProjects()
  const create = useCreateProject()
  const [name, setName] = useState('')
  const [search, setSearch] = useState('')

  const open = (project: { id: string }) =>
    void navigate({ to: '/projects/$projectId', params: { projectId: project.id } })

  const text = search.trim().toLowerCase()
  const rows = (data ?? []).filter(
    (p) =>
      !text ||
      [p.name, p.short_code, p.approval_reference, p.status]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(text)
  )

  const columns: Array<Column<Project>> = [
    {
      id: 'code',
      header: 'Code',
      cell: (p) => (
        <span className="font-mono text-xs font-semibold">{p.short_code}</span>
      ),
      sortValue: (p) => p.short_code,
    },
    {
      id: 'name',
      header: 'Project',
      cell: (p) => (
        <div className="min-w-0">
          <span className="block truncate font-semibold">{p.name}</span>
          <span className="block truncate text-xs text-[rgb(var(--foreground-muted))]">
            {p.approval_reference || 'No approval reference yet'}
          </span>
        </div>
      ),
      sortValue: (p) => p.name.toLowerCase(),
    },
    {
      id: 'status',
      header: 'Status',
      cell: (p) => (
        <Badge tone={projectTone(p.status)}>
          {PROJECT_STATUS_LABELS[p.status] ?? p.status}
        </Badge>
      ),
      sortValue: (p) => p.status,
    },
    {
      id: 'documents',
      header: 'Documents',
      cell: (p) => (
        <span className="text-sm">
          {p.documents_approved ? 'approved' : 'not included'}
        </span>
      ),
      sortValue: (p) => String(p.documents_approved),
    },
    {
      id: 'created',
      header: 'Created',
      cell: (p) => <span className="text-sm">{shortDate(p.created_at)}</span>,
      sortValue: (p) => p.created_at ?? '',
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Projects"
        description="Research projects asking for a safe copy of patients' submitted data. Each project picks its patients; its safe copy goes to the Zone 2 inbox for review before release."
      />

      <Can permission="project:create">
        <Card className="p-5">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault()
              if (!name.trim()) return
              void create
                .mutateAsync({ name: name.trim() })
                .then((project) => {
                  setName('')
                  open(project)
                })
                .catch(() => undefined)
            }}
          >
            <div className="min-w-64 flex-1">
              <TextField
                label="New project"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. Readmissions study 2026"
                aria-label="New project name"
              />
            </div>
            <Button
              type="submit"
              disabled={!name.trim()}
              isLoading={create.isPending}
              leadingIcon={<Plus className="size-4" aria-hidden="true" />}
            >
              Create project
            </Button>
          </form>
        </Card>
      </Can>

      <div className="rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4">
        <TextField
          label="Search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search by name, code, approval or status..."
          aria-label="Search projects"
        />
      </div>

      <DataTable
        data={rows}
        columns={columns}
        getRowId={(p) => p.id}
        isLoading={isLoading}
        isFetching={isFetching}
        error={error}
        loadingLabel="Loading projects"
        emptyMessage="No projects yet."
        rowActions={(p) => (
          <Button size="sm" variant="outline" onClick={() => open(p)}>
            Open
          </Button>
        )}
      />
    </div>
  )
}
