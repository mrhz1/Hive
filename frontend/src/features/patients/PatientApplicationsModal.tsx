import { useNavigate } from '@tanstack/react-router'
import { X } from 'lucide-react'
import { useEffect } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { useApplications } from '@/hooks/useResources'
import { patientName, type Patient } from '@/schemas/patient'
import { applicationTone } from '@/schemas/patientApplication'

/** Hive TIMESTAMPs arrive as naive ISO strings; the seconds add nothing. */
function moment(value: string | null | undefined): string {
  return value ? value.slice(0, 16).replace('T', ' ') : '—'
}

/**
 * This patient's applications, without leaving the patient list.
 *
 * Finding one used to mean going to Applications and searching by name,
 * which only works if you can spell it the way it was entered and there
 * is only one of them. Opening a row goes to the wizard, which is where
 * an application is worked on either way.
 */
export function PatientApplicationsModal({
  patient,
  onClose,
}: {
  patient: Patient
  onClose: () => void
}) {
  const navigate = useNavigate()
  const { data, isLoading, error } = useApplications(patient.id)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const applications = data ?? []

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-[rgb(var(--background))]/80 p-4 backdrop-blur-sm sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label={`Applications for ${patientName(patient)}`}
    >
      <div className="mx-auto flex max-h-full w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] shadow-xl">
        <div className="flex items-center justify-between gap-4 border-b border-[rgb(var(--border))] px-5 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-bold">
              {patientName(patient)}
            </p>
            <p className="truncate font-mono text-xs text-[rgb(var(--foreground-muted))]">
              {patient.id}
            </p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            aria-label="Close applications"
          >
            <X className="size-4" aria-hidden="true" />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto p-5">
          {isLoading ? (
            <LoadingBlock label="Loading applications" />
          ) : error ? (
            <p className="text-sm text-[rgb(var(--foreground-muted))]">
              The applications could not be loaded.
            </p>
          ) : applications.length === 0 ? (
            <p className="text-sm text-[rgb(var(--foreground-muted))]">
              This patient has no applications yet.
            </p>
          ) : (
            <ul className="space-y-2">
              {applications.map((application) => (
                <li
                  key={application.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] px-4 py-3"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={applicationTone(application.status)}>
                        {application.status}
                      </Badge>
                      <span className="font-mono text-xs text-[rgb(var(--foreground-muted))]">
                        {application.id}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
                      Created {moment(application.created_at)}
                      {application.assigned_to_username
                        ? ` · ${application.assigned_to_username}`
                        : ''}
                      {application.description
                        ? ` · ${application.description}`
                        : ''}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    aria-label={`Open application ${application.id}`}
                    onClick={() => {
                      onClose()
                      void navigate({
                        to: '/applications/$applicationId',
                        params: { applicationId: application.id },
                      })
                    }}
                  >
                    Open
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
