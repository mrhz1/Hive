import { AlertTriangle, Cpu } from 'lucide-react'
import { Badge, Card } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import { useIntakeBatchProgress, useIntakeProgress } from '@/hooks/useResources'
import { humanDuration, type IntakeWorker } from '@/schemas/intake'

const formatNumber = (n: number) => n.toLocaleString()

const titleClass =
  'text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase'
const labelClass = 'text-xs text-[rgb(var(--foreground-muted))]'

function ProgressBar({ percent, red = false }: { percent: number; red?: boolean }) {
  const width = Math.max(0, Math.min(100, percent))
  const color = red ? 'bg-rose-500' : 'bg-[rgb(var(--primary))]'

  return (
    <div
      className="h-2.5 w-full overflow-hidden rounded-full bg-[rgb(var(--background-secondary))]"
      role="progressbar"
      aria-valuenow={Math.round(width)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={`h-full rounded-full transition-[width] duration-700 ${color}`}
        style={{ width: `${width}%` }}
      />
    </div>
  )
}

function WorkerRow({ worker }: { worker: IntakeWorker }) {
  let dotColor = 'bg-[rgb(var(--foreground-muted))]'
  let badgeTone: 'danger' | 'success' | 'neutral' = 'neutral'
  if (!worker.alive) {
    dotColor = 'bg-rose-500'
    badgeTone = 'danger'
  } else if (worker.status === 'working') {
    dotColor = 'bg-emerald-500'
    badgeTone = 'success'
  }

  const shards =
    worker.of > 1 ? `shards ${worker.shards.join(', ')} of ${worker.of}` : 'all shards'
  const lastSeen =
    worker.seconds_since_seen < 60
      ? `${Math.round(worker.seconds_since_seen)}s ago`
      : `${humanDuration(worker.seconds_since_seen)} ago`

  let currentFiles = ''
  if (worker.alive && worker.current.length > 0) {
    currentFiles = 'on ' + worker.current.slice(0, 3).join(', ')
    if (worker.current.length > 3) {
      currentFiles += ` +${worker.current.length - 3}`
    }
  }

  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-[rgb(var(--border))] py-2 first:border-0">
      <span className="flex min-w-48 items-center gap-2">
        <span className={`size-2 rounded-full ${dotColor}`} aria-hidden="true" />
        <span className="font-mono text-xs font-semibold">{worker.name}</span>
      </span>
      <span className={labelClass}>
        {shards} · {worker.workers} at once
      </span>
      <Badge tone={badgeTone}>{worker.alive ? worker.status : 'stopped'}</Badge>
      <span className="text-xs tabular-nums">{formatNumber(worker.per_hour)}/h</span>
      <span className={labelClass}>seen {lastSeen}</span>
      {currentFiles && (
        <span
          className="min-w-0 flex-1 truncate font-mono text-[11px] text-[rgb(var(--foreground-muted))]"
          title={worker.current.join(', ')}
        >
          {currentFiles}
        </span>
      )}
    </li>
  )
}

export function IntakeProgressPanel() {
  const { data: progress, isLoading } = useIntakeProgress()
  const { data: batches } = useIntakeBatchProgress()

  if (isLoading) {
    return (
      <Card className="p-5">
        <Spinner size="md" label="Loading progress" />
      </Card>
    )
  }
  if (!progress) return null

  return (
    <div className="space-y-3">
      {progress.stalled && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-700 dark:text-rose-300"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-bold">De-identification has stopped</p>
            <p className="mt-0.5">{progress.stalled_reason}</p>
          </div>
        </div>
      )}

      <Card className="p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className={titleClass}>De-identification</h2>
          <span className={labelClass}>updates every 10 seconds</span>
        </div>

        <p className="mt-2 text-2xl font-bold tabular-nums">
          {formatNumber(progress.finished)}{' '}
          <span className="text-base font-normal text-[rgb(var(--foreground-muted))]">
            of {formatNumber(progress.total)} files processed
          </span>{' '}
          <span className="text-base">({progress.percent.toFixed(1)}%)</span>
        </p>

        <div className="mt-3">
          <ProgressBar percent={progress.percent} red={progress.stalled} />
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-5">
          <div>
            <dt className={labelClass}>Remaining</dt>
            <dd className="font-semibold tabular-nums">
              {formatNumber(progress.remaining)}
            </dd>
          </div>
          <div>
            <dt className={labelClass}>Speed</dt>
            <dd className="font-semibold tabular-nums">
              {progress.per_hour > 0 ? `${formatNumber(progress.per_hour)} / hour` : '-'}
            </dd>
          </div>
          <div>
            <dt className={labelClass}>Time left</dt>
            <dd className="font-semibold">
              {progress.remaining === 0 ? 'done' : humanDuration(progress.eta_seconds)}
            </dd>
          </div>
          <div>
            <dt className={labelClass}>Failed</dt>
            <dd
              className={`font-semibold tabular-nums ${progress.failed ? 'text-rose-600 dark:text-rose-400' : ''}`}
            >
              {formatNumber(progress.failed)}
            </dd>
          </div>
          <div>
            <dt className={labelClass}>Need a person</dt>
            <dd className="font-semibold tabular-nums">
              {formatNumber(progress.needs_a_person)}
            </dd>
          </div>
        </dl>
      </Card>

      <Card className="p-5">
        <h2 className={`flex items-center gap-2 ${titleClass}`}>
          <Cpu className="size-3.5" aria-hidden="true" /> Workers
        </h2>
        {progress.workers.length === 0 ? (
          <p className="mt-2 text-sm text-[rgb(var(--foreground-muted))]">
            No worker has reported yet. Start one with <code>make intake-watch</code>, or
            the scheduled Job.
          </p>
        ) : (
          <ul className="mt-2">
            {progress.workers.map((worker) => (
              <WorkerRow key={worker.name ?? ''} worker={worker} />
            ))}
          </ul>
        )}
      </Card>

      {batches && batches.length > 0 && (
        <Card className="p-5">
          <h2 className={titleClass}>Pushes</h2>
          <ul className="mt-2 space-y-3">
            {batches.slice(0, 8).map((batch) => {
              let summary = `${formatNumber(batch.finished)} / ${formatNumber(batch.total)}`
              if (batch.failed) summary += ` · ${formatNumber(batch.failed)} failed`
              if (batch.needs_a_person)
                summary += ` · ${formatNumber(batch.needs_a_person)} need a person`

              return (
                <li key={batch.id}>
                  <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                    <span className="text-[rgb(var(--foreground-muted))]">
                      {batch.started_at
                        ? new Date(batch.started_at).toLocaleString()
                        : batch.id}
                    </span>
                    <span className="tabular-nums">{summary}</span>
                  </div>
                  <div className="mt-1">
                    <ProgressBar percent={batch.percent} />
                  </div>
                </li>
              )
            })}
          </ul>
        </Card>
      )}
    </div>
  )
}
