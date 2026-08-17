import { Badge, Card, DescriptionItem } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { useApplicationFiles, userHooks } from '@/hooks/useResources'
import { userLabel } from '@/schemas/user'
import { patientName, type Patient } from '@/schemas/patient'
import {
  applicationTone,
  type PatientApplication,
} from '@/schemas/patientApplication'
import {
  deidTone,
  formatFileSize,
  rejectedCount,
  reviewTone,
  undecidedCount,
} from '@/schemas/applicationFile'

/** A patient field worth showing back, and only if it has a value. */
function Detail({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null
  return <DescriptionItem label={label}>{value}</DescriptionItem>
}

/** Hive TIMESTAMPs arrive as naive ISO strings; the seconds add nothing. */
function moment(value: string | null | undefined): string | null {
  return value ? value.slice(0, 16).replace('T', ' ') : null
}

/**
 * One thing that happened to the application: when, and at whose hand.
 *
 * Both halves, always. The username answers who without anybody having
 * to go and look an id up, and the id is kept beside it because it is
 * what the audit trail and the access log are keyed on -- two people
 * can share a display name, and only one of them did this.
 */
function Event({
  label,
  at,
  userId,
  username,
}: {
  label: string
  at: string | null | undefined
  userId: string | null | undefined
  username: string | null | undefined
}) {
  const when = moment(at)
  if (!when && !userId) return null

  return (
    <DescriptionItem label={label}>
      <span className="tabular-nums">{when ?? 'not recorded'}</span>
      {userId ? (
        <>
          {' · '}
          <span>{username ?? 'unknown user'}</span>{' '}
          <span className="font-mono text-xs text-[rgb(var(--foreground-muted))]">
            {userId}
          </span>
        </>
      ) : null}
    </DescriptionItem>
  )
}

export function ApplicationSummary({
  patient,
  application,
}: {
  patient: Patient
  application?: PatientApplication
}) {
  const filesQuery = useApplicationFiles(application?.id)
  const files = filesQuery.data ?? []

  const rejected = rejectedCount(files)
  const undecided = undecidedCount(files)
  const approved = files.length - rejected - undecided

  // Only to put a name to the id the application carries.
  const usersQuery = userHooks.useList({ enabled: Boolean(application?.assigned_to_id) })
  const assignee = usersQuery.data?.find(
    (user) => user.id === application?.assigned_to_id
  )

  return (
    <div className="space-y-6">
      {application ? (
        <Card className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
              Application
            </h2>
            <Badge tone={applicationTone(application.status)}>
              {application.status}
            </Badge>
          </div>

          <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
            <Event
              label="Created"
              at={application.created_at}
              userId={application.created_by_id}
              username={application.created_by_username}
            />
            <Event
              label="Submitted"
              at={application.submitted_at}
              userId={application.submitted_by_id}
              username={application.submitted_by_username}
            />
            {/* The same pair of columns carries both verdicts, so the
                heading has to say which one this was. */}
            <Event
              label={application.status === 'rejected' ? 'Rejected' : 'Reviewed'}
              at={application.reviewed_at}
              userId={application.reviewed_by_id}
              username={application.reviewed_by_username}
            />
            <DescriptionItem label="Assigned to">
              {assignee ? (
                userLabel(assignee)
              ) : application.assigned_to_id ? (
                // The API resolves the username for exactly this case:
                // somebody with `application:view` and no `user:view`
                // gets a name rather than a uuid.
                (application.assigned_to_username ?? application.assigned_to_id)
              ) : (
                <span className="text-[rgb(var(--foreground-muted))]">Nobody</span>
              )}
            </DescriptionItem>
            <Detail label="Description" value={application.description} />
            {application.status_reason ? (
              <DescriptionItem
                label={
                  application.status === 'rejected'
                    ? 'Why it was rejected'
                    : 'Reason'
                }
              >
                {application.status_reason}
              </DescriptionItem>
            ) : null}
            {application.original_file_path ? (
              <DescriptionItem label="Source folder">
                <span className="font-mono text-xs break-all">
                  {application.original_file_path}
                </span>
              </DescriptionItem>
            ) : null}
            <DescriptionItem label="Application id">
              <span className="font-mono text-xs break-all">{application.id}</span>
            </DescriptionItem>
          </dl>
        </Card>
      ) : null}

      <Card className="p-5">
        <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
          Patient
        </h2>

        <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
          <DescriptionItem label="Name">{patientName(patient)}</DescriptionItem>
          <DescriptionItem label="Patient id">
            <span className="font-mono text-xs">{patient.id}</span>
          </DescriptionItem>
          <Detail label="Date of birth" value={patient.dt_b} />
          <Detail label="Email" value={patient.ptemail} />
          <Detail label="Phone" value={patient.ptphone} />
          <Detail label="Street" value={patient.ptstreet} />
          <Detail label="City" value={patient.ptcity} />
          <Detail label="State" value={patient.ptstate} />
          <Detail label="ZIP" value={patient.ptzip} />
          <Detail label="Country" value={patient.ptcountry} />
          <Detail label="Institution" value={patient.instcode || patient.pname} />
          <Detail label="Registered" value={patient.dt_reg} />
          <Detail label="Original file path" value={patient.original_file_path} />
          <Detail
            label="De-identified file path"
            value={patient.deidentified_file_path}
          />
        </dl>
      </Card>

      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
            Documents ({files.length})
          </h2>
          {files.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              <Badge tone="success">{approved} approved</Badge>
              {rejected > 0 ? (
                <Badge tone="danger">{rejected} rejected</Badge>
              ) : null}
              {undecided > 0 ? (
                <Badge tone="neutral">{undecided} undecided</Badge>
              ) : null}
            </div>
          ) : null}
        </div>

        {filesQuery.isLoading ? (
          <LoadingBlock label="Loading documents" />
        ) : files.length === 0 ? (
          <p className="mt-4 text-sm text-[rgb(var(--foreground-muted))]">
            No documents were attached to this application.
          </p>
        ) : (
          <ul className="mt-4 space-y-2">
            {files.map((file) => (
              <li
                key={file.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] px-4 py-3"
              >
                <div className="min-w-0">
                  <span className="block truncate text-sm font-semibold">
                    {file.original_file_name}
                  </span>
                  <span className="block truncate text-xs text-[rgb(var(--foreground-muted))]">
                    {formatFileSize(file.file_size)}
                    {file.description ? ` · ${file.description}` : ''}
                  </span>
                  {/* The reason a document was turned down, where the
                      verdict is: whoever has to fix it reads this page
                      and would otherwise have to go back to step 2. */}
                  {file.review_status === 'rejected' && file.review_note ? (
                    <span className="mt-0.5 block text-xs text-[rgb(var(--foreground-muted))]">
                      {file.review_note}
                    </span>
                  ) : null}
                </div>
                <div className="flex shrink-0 flex-wrap gap-1.5">
                  <Badge tone={reviewTone(file.review_status)}>
                    {file.review_status}
                  </Badge>
                  <Badge tone={deidTone(file.deid_status)}>
                    {file.deid_status}
                  </Badge>
                  {file.is_deidentified ? (
                    <Badge tone="success">de-identified</Badge>
                  ) : (
                    <Badge tone="warning">not de-identified</Badge>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
