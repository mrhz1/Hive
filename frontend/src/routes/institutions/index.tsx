import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { Pencil, Plus, Save, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable, type Column } from '@/components/DataTable'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/Field'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { usePermissions } from '@/hooks/useCurrentUser'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { ApiError } from '@/lib/api/client'
import { institutionsApi } from '@/lib/api/resources'
import { queryKeys } from '@/lib/queryKeys'
import type { Institution } from '@/schemas/qc'

export const Route = createFileRoute('/institutions/')({
  component: () => (
    <RequirePermission permission="institution:view">
      <InstitutionsPage />
    </RequirePermission>
  ),
})

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

type Draft = { code: string; name: string; email: string; isNew: boolean }

function InstitutionsPage() {
  useDocumentTitle('Sites')
  const { can } = usePermissions()
  const client = useQueryClient()
  const list = useQuery({
    queryKey: queryKeys.institutions,
    queryFn: institutionsApi.list,
  })
  const [draft, setDraft] = useState<Draft | null>(null)

  const refresh = () =>
    void client.invalidateQueries({ queryKey: queryKeys.institutions })
  const save = useMutation({
    mutationFn: (d: Draft) =>
      institutionsApi.save(d.code, {
        name: d.name.trim() || null,
        contact_email: d.email.trim() || null,
      }),
    onSuccess: (saved) => {
      toast.success(`${saved.code} saved`)
      setDraft(null)
      refresh()
    },
    onError: (error) => toast.error(message(error, 'Could not save')),
  })
  const remove = useMutation({
    mutationFn: institutionsApi.remove,
    onSuccess: () => {
      toast.success('Contact removed')
      refresh()
    },
    onError: (error) => toast.error(message(error, 'Could not remove')),
  })

  const rows = list.data ?? []
  const missing = rows.filter((r) => r.patients > 0 && !r.contact_email).length

  const columns: Array<Column<Institution>> = [
    {
      id: 'code',
      header: 'Code',
      cell: (i) => <span className="font-mono text-xs font-semibold">{i.code}</span>,
      sortValue: (i) => i.code,
    },
    {
      id: 'name',
      header: 'Site',
      cell: (i) => i.name ?? '—',
      sortValue: (i) => i.name ?? '',
    },
    {
      id: 'email',
      header: 'Contact email',
      cell: (i) =>
        i.contact_email ? (
          <span className="text-sm">{i.contact_email}</span>
        ) : (
          <Badge tone="warning">no contact</Badge>
        ),
      sortValue: (i) => i.contact_email ?? '',
    },
    {
      id: 'patients',
      header: 'Patients',
      cell: (i) => i.patients,
      sortValue: (i) => i.patients,
      isNumeric: true,
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Sites"
        description="The contact of each site that submits patients. When an application is rejected, the reason is emailed to the contact of the patient's institution (protocol 9.1.2 step 7). Codes come from the patients' institution code."
        actions={
          <Can permission="institution:manage">
            <Button
              leadingIcon={<Plus className="size-4" aria-hidden="true" />}
              onClick={() => setDraft({ code: '', name: '', email: '', isNew: true })}
            >
              Add site
            </Button>
          </Can>
        }
      />

      {draft ? (
        <Card className="p-5">
          <h2 className="text-sm font-bold">
            {draft.isNew ? 'Add a site' : `Edit ${draft.code}`}
          </h2>
          <form
            className="mt-4 grid gap-3 md:grid-cols-3"
            onSubmit={(event) => {
              event.preventDefault()
              save.mutate(draft)
            }}
          >
            <TextField
              label="Institution code"
              required
              disabled={!draft.isNew}
              value={draft.code}
              onChange={(event) =>
                setDraft({ ...draft, code: event.target.value.toUpperCase() })
              }
            />
            <TextField
              label="Site name"
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            />
            <TextField
              label="Contact email"
              type="email"
              value={draft.email}
              placeholder="coordinator@site.org"
              onChange={(event) => setDraft({ ...draft, email: event.target.value })}
            />
            <div className="flex gap-2 md:col-span-3">
              <Button
                type="submit"
                disabled={!draft.code.trim()}
                isLoading={save.isPending}
                leadingIcon={<Save className="size-4" aria-hidden="true" />}
              >
                Save
              </Button>
              <Button
                variant="outline"
                leadingIcon={<X className="size-4" aria-hidden="true" />}
                onClick={() => setDraft(null)}
              >
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      ) : null}

      <Card className="space-y-3 p-5">
        {missing > 0 ? (
          <p className="text-sm">
            <Badge tone="warning">{missing}</Badge> site(s) with patients have no contact,
            so their rejections are only emailed to the CHSS team.
          </p>
        ) : null}
        <DataTable
          data={rows}
          columns={columns}
          getRowId={(i) => i.code}
          isLoading={list.isLoading}
          isFetching={list.isFetching}
          error={list.error}
          loadingLabel="Loading sites"
          emptyMessage="No institution codes yet."
          rowActions={
            can('institution:manage')
              ? (i) => (
                  <div className="flex justify-end gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      leadingIcon={<Pencil className="size-3.5" aria-hidden="true" />}
                      onClick={() =>
                        setDraft({
                          code: i.code,
                          name: i.name ?? '',
                          email: i.contact_email ?? '',
                          isNew: false,
                        })
                      }
                    >
                      Edit
                    </Button>
                    {i.updated_at ? (
                      <Button
                        size="sm"
                        variant="outline"
                        aria-label={`Remove the contact of ${i.code}`}
                        isLoading={remove.isPending && remove.variables === i.code}
                        onClick={() => remove.mutate(i.code)}
                      >
                        <Trash2 className="size-3.5" aria-hidden="true" />
                      </Button>
                    ) : null}
                  </div>
                )
              : undefined
          }
        />
      </Card>
    </div>
  )
}
