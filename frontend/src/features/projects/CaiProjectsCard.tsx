import { CalendarPlus, CloudUpload, ExternalLink, FlaskConical, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { ReasonDialog } from '@/components/ReasonDialog'
import { Button } from '@/components/ui/Button'
import { Badge, Card } from '@/components/ui/Misc'
import { usePermissions } from '@/hooks/useCurrentUser'
import {
  useCaiProjects,
  useCaiReleaseStatus,
  useCreateCaiProject,
  useEndCaiProject,
  useExtendCaiProject,
  useSyncCaiStaging,
} from '@/hooks/useResources'
import { daysLeft } from '@/schemas/abstraction'
import type { CaiProject, ProjectDetail } from '@/schemas/project'

const titleClass =
  'text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase'
const mutedClass = 'text-xs text-[rgb(var(--foreground-muted))]'

type Dialog = { kind: 'extend' | 'end'; record: CaiProject } | null

export function CaiProjectsCard({ project }: { project: ProjectDetail }) {
  const { can } = usePermissions()
  const allowed = can('cai:provision')
  const records = useCaiProjects(project.id, allowed)
  const status = useCaiReleaseStatus(project.id, allowed)
  const create = useCreateCaiProject(project.id)
  const sync = useSyncCaiStaging(project.id)
  const extend = useExtendCaiProject()
  const end = useEndCaiProject()
  const [dialog, setDialog] = useState<Dialog>(null)

  // Only admins hold cai:provision; everyone else never sees this card.
  if (!allowed) return null

  const ended = project.status === 'ended'
  const all = records.data ?? []
  const active = all.filter((r) => r.status === 'active')
  const removed = all.filter((r) => r.status !== 'active')
  const byUser = new Map(active.map((r) => [r.user_id, r]))
  const release = status.data
  // Creating a project copies any missing release files to staging first, so
  // "not in staging" doesn't block it.
  const ready = Boolean(release?.release_id && !release.error)

  let blocker: string | null = null
  let note: string | null = null
  if (ended) blocker = 'The project has ended.'
  else if (status.isLoading) blocker = 'Checking the staging project…'
  else if (status.error) blocker = 'Could not check the staging project.'
  else if (release?.error) blocker = `Cloudera AI: ${release.error}`
  else if (!release?.release_id)
    blocker = 'The project has no approved Zone 2 release yet.'
  else if (!release.in_staging)
    note = `Release ${release.release_id} is not in the staging project yet. It is copied there automatically after approval; if that didn't happen, copy it now. Creating a project also copies it first.`

  return (
    <Card className="p-5">
      <div className="max-w-2xl">
        <h2 className={titleClass}>Cloudera AI projects (Zone 2)</h2>
        <p className={`mt-1 ${mutedClass}`}>
          Each member gets their own private Cloudera AI project holding only this
          project's latest approved release, where they can run their own code. Access
          ends after 6 months unless extended, and when the project ends. Researchers find
          it under <strong>Scope → My Team Projects</strong>; send them the link.
          Resources (CPU, memory) are chosen per session; limits are set by Expedition
          support.
        </p>
      </div>

      {release?.release_id ? (
        <p className="mt-3 text-sm">
          Release <span className="font-mono">{release.release_id}</span>{' '}
          {release.in_staging ? (
            <Badge tone="success">in staging</Badge>
          ) : (
            <Badge tone="warning">not in staging</Badge>
          )}
        </p>
      ) : null}
      {blocker ? <p className={`mt-2 ${mutedClass}`}>{blocker}</p> : null}
      {note ? (
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <p className={mutedClass}>{note}</p>
          <Button
            size="sm"
            variant="outline"
            disabled={ended || sync.isPending}
            isLoading={sync.isPending}
            leadingIcon={<CloudUpload className="size-3.5" aria-hidden="true" />}
            onClick={() => sync.mutate(undefined)}
          >
            Copy to staging
          </Button>
        </div>
      ) : null}

      <ul className="mt-3 divide-y divide-[rgb(var(--border))] text-sm">
        {project.members.map((member) => {
          const record = byUser.get(member.user_id)
          const left = daysLeft(record?.expires_at)
          return (
            <li
              key={member.id}
              className="flex flex-wrap items-center justify-between gap-3 py-2"
            >
              <div className="min-w-0">
                <div>{member.username ?? member.user_id}</div>
                {record ? (
                  <div className={mutedClass}>
                    {record.files.length} file(s) from release{' '}
                    <span className="font-mono">{record.release_id}</span>
                    {record.url ? (
                      <>
                        {' · '}
                        <a
                          href={record.url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 underline"
                        >
                          open <ExternalLink className="size-3" aria-hidden="true" />
                        </a>
                      </>
                    ) : null}
                  </div>
                ) : null}
              </div>
              {record ? (
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={left !== null && left <= 14 ? 'warning' : 'success'}>
                    {left !== null && left <= 0
                      ? 'expired'
                      : `until ${(record.expires_at ?? '').slice(0, 10)}`}
                  </Badge>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={ended}
                    leadingIcon={<CalendarPlus className="size-3.5" aria-hidden="true" />}
                    onClick={() => setDialog({ kind: 'extend', record })}
                  >
                    Extend 6 months
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    leadingIcon={<Trash2 className="size-3.5" aria-hidden="true" />}
                    onClick={() => setDialog({ kind: 'end', record })}
                  >
                    Remove
                  </Button>
                </div>
              ) : (
                <Button
                  size="sm"
                  disabled={!ready || create.isPending}
                  title={blocker ?? undefined}
                  isLoading={create.isPending && create.variables === member.user_id}
                  leadingIcon={<FlaskConical className="size-3.5" aria-hidden="true" />}
                  onClick={() => create.mutate(member.user_id)}
                >
                  Create Cloudera AI project
                </Button>
              )}
            </li>
          )
        })}
        {project.members.length === 0 ? (
          <li className={`py-2 ${mutedClass}`}>Add members first.</li>
        ) : null}
      </ul>

      {create.isPending ? (
        <p className={`mt-2 ${mutedClass}`}>
          Copying the staging project and removing what this member may not see. This can
          take a few minutes; keep the page open.
        </p>
      ) : null}

      {removed.length > 0 ? (
        <details className="mt-3 text-sm">
          <summary className={`cursor-pointer ${mutedClass}`}>
            {removed.length} removed project(s)
          </summary>
          <ul className="mt-2 space-y-1">
            {removed.map((r) => (
              <li key={r.id} className={mutedClass}>
                {r.username ?? r.cai_username}, release {r.release_id}, removed{' '}
                {(r.ended_at ?? '').slice(0, 10)}
                {r.ended_reason ? ` (${r.ended_reason})` : ''}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {dialog?.kind === 'extend' ? (
        <ReasonDialog
          title={`Keep ${dialog.record.cai_username}'s access 6 more months?`}
          description="Extending needs an approval. Record which one; it goes in the audit log."
          confirmLabel="Extend"
          placeholder="e.g. REB renewal 2027, approved by the CHSS manager"
          isBusy={extend.isPending}
          onCancel={() => setDialog(null)}
          onConfirm={(reason) =>
            void extend
              .mutateAsync({ id: dialog.record.id, reason })
              .then(() => setDialog(null))
              .catch(() => undefined)
          }
        />
      ) : null}
      {dialog?.kind === 'end' ? (
        <ReasonDialog
          title={`Delete ${dialog.record.cai_username}'s Cloudera AI project?`}
          description="The project and everything in it, including the researcher's own code, is deleted in Cloudera AI. A new one can be made later."
          confirmLabel="Delete project"
          placeholder="e.g. analysis finished, code committed to GitLab"
          isBusy={end.isPending}
          onCancel={() => setDialog(null)}
          onConfirm={(reason) =>
            void end
              .mutateAsync({ id: dialog.record.id, reason })
              .then(() => setDialog(null))
              .catch(() => undefined)
          }
        />
      ) : null}
    </Card>
  )
}
