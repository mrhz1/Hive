import { Badge, Card, DescriptionItem } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { useApplicationFiles, userHooks } from '@/hooks/useResources'
import { userLabel } from '@/schemas/user'
import { patientName, type Patient } from '@/schemas/patient'
import {
  applicationTone,
  type PatientApplication,
} from '@/schemas/patientApplication'
import { deidTone, formatFileSize } from '@/schemas/applicationFile'

/** A patient field worth showing back, and only if it has a value. */
function Detail({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null
  return <DescriptionItem label={label}>{value}</DescriptionItem>
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

  // Only to put a name to the id the application carries.
  const usersQuery = userHooks.useList({ enabled: Boolean(application?.assigned_to_id) })
  const assignee = usersQuery.data?.find(
    (user) => user.id === application?.assigned_to_id
  )

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
            Patient
          </h2>
          {application ? (
            <Badge tone={applicationTone(application.status)}>
              {application.status}
            </Badge>
          ) : null}
        </div>

        <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
          <DescriptionItem label="Name">{patientName(patient)}</DescriptionItem>
          {application ? (
            <DescriptionItem label="Assigned to">
              {assignee ? (
                userLabel(assignee)
              ) : application.assigned_to_id ? (
                application.assigned_to_id
              ) : (
                <span className="text-[rgb(var(--foreground-muted))]">Nobody</span>
              )}
            </DescriptionItem>
          ) : null}
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
        <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
          Documents ({files.length})
        </h2>

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
                </div>
                <div className="flex shrink-0 flex-wrap gap-1.5">
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
