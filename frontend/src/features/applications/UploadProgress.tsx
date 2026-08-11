import { CheckCircle2, X, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Badge, Card } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import {
  isUploadJobSettled,
  uploadJobSummary,
  uploadJobTone,
  type UploadJob,
} from '@/schemas/applicationFile'

/**
 * What a background batch is doing.
 *
 * The wizard no longer waits for the upload, so this is the only place a
 * user can see that files are still moving -- and, more importantly, the
 * only place they see which ones did not make it. The same list goes out
 * by email to whoever the application is assigned to.
 */
export function UploadProgress({
  job,
  onDismiss,
}: {
  job: UploadJob
  onDismiss?: () => void
}) {
  const settled = isUploadJobSettled(job)
  const failures = job.files.filter((file) => file.status === 'failed')

  const done = job.stored + job.failed
  const percent = job.total > 0 ? Math.round((done / job.total) * 100) : 0

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          {settled ? (
            job.status === 'done' ? (
              <CheckCircle2
                className="size-4 text-[rgb(var(--success))]"
                aria-hidden="true"
              />
            ) : (
              <XCircle
                className="size-4 text-[rgb(var(--danger))]"
                aria-hidden="true"
              />
            )
          ) : (
            <Spinner size="sm" label="" />
          )}
          <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
            Upload
          </h2>
          <Badge tone={uploadJobTone(job.status)}>{job.status}</Badge>
        </div>

        {settled && onDismiss ? (
          <Button
            size="sm"
            variant="outline"
            aria-label="Dismiss the upload report"
            leadingIcon={<X className="size-3.5" aria-hidden="true" />}
            onClick={onDismiss}
          >
            Dismiss
          </Button>
        ) : null}
      </div>

      <p
        className="mt-3 text-sm text-[rgb(var(--foreground-muted))]"
        role="status"
        aria-live="polite"
      >
        {uploadJobSummary(job)}
      </p>

      {!settled ? (
        <div
          className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-[rgb(var(--background-secondary))]"
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Files moved into storage"
        >
          <div
            className="h-full rounded-full bg-[rgb(var(--primary))] transition-[width] duration-500"
            style={{ width: `${percent}%` }}
          />
        </div>
      ) : null}

      {failures.length > 0 ? (
        <ul className="mt-4 space-y-1.5">
          {failures.map((file) => (
            <li
              key={file.name}
              className="rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] px-3 py-2 text-xs"
            >
              <span className="font-semibold">{file.name}</span>
              {file.error ? (
                <span className="text-[rgb(var(--foreground-muted))]">
                  {' '}
                  — {file.error}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  )
}
