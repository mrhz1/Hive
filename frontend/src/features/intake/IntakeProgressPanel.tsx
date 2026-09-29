import { AlertTriangle, Cpu } from 'lucide-react'
import { Badge, Card } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import { useIntakeBatchProgress, useIntakeProgress } from '@/hooks/useResources'
import { humanDuration, type IntakeWorker } from '@/schemas/intake'

const number = new Intl.NumberFormat()

function Bar({ percent, tone = 'primary' }: { percent: number; tone?: 'primary' | 'danger' }) {
  const width = Math.max(0, Math.min(100, percent))
  return (
    <div
      className="h-2.5 w-full overflow-hidden rounded-full bg-[rgb(var(--background-secondary))]"
      role="progressbar"
      aria-valuenow={Math.round(width)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={
          'h-full rounded-full transition-[width] duration-700 ' +
          (tone === 'danger' ? 'bg-rose-500' : 'bg-[rgb(var(--primary))]')
        }
        style={{ width: `${width}%` }}
      />
    </div>
  )
}

function ago(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  return `${humanDuration(seconds)} ago`
}

function WorkerRow({ worker }: { worker: IntakeWorker }) {
  const shards =
    worker.of > 1 ? `shards ${worker.shards.join(', ')} of ${worker.of}` : 'all shards'
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-[rgb(var(--border))] py-2 first:border-0">
      <span className="flex min-w-48 items-center gap-2">
        <span
          className={
            'size-2 rounded-full ' +
            (!worker.alive
              ? 'bg-rose-500'
              : worker.status === 'working'
                ? 'bg-emerald-500'
                : 'bg-[rgb(var(--foreground-muted))]')
          }
          aria-hidden="true"
        />
        <span className="font-mono text-xs font-semibold">{worker.name}</span>
      </span>
      <span className="text-xs text-[rgb(var(--foreground-muted))]">
        {shards} · {worker.workers} at once
      </span>
      <Badge tone={!worker.alive ? 'danger' : worker.status === 'working' ? 'success' : 'neutral'}>
        {worker.alive ? worker.status : 'stopped'}
      </Badge>
      <span className="text-xs tabular-nums">{number.format(worker.per_hour)}/h</span>
      <span className="text-xs text-[rgb(var(--foreground-muted))]">
        seen {ago(worker.seconds_since_seen)}
      </span>
      {worker.alive && worker.current.length ? (
        <span
          className="min-w-0 flex-1 truncate font-mono text-[11px] text-[rgb(var(--foreground-muted))]"
          title={worker.current.join(', ')}
        >
          on {worker.current.slice(0, 3).join(', ')}
          {worker.current.length > 3 ? ` +${worker.current.length - 3}` : ''}
        </span>
      ) : null}
    </li>
  )
}

/**
 * How far along de-identification is, how fast, how long to go, and --
 * most important at five million files -- whether it has stopped.
 */
export function IntakeProgressPanel() {
  const progress = useIntakeProgress()
  const batches = useIntakeBatchProgress()

  if (progress.isLoading) {
    return (
      <Card className="p-5">
        <Spinner size="md" label="Loading progress" />
      </Card>
    )
  }
  const p = progress.data
  if (!p) return null

  return (
    <div className="space-y-3">
      {p.stalled ? (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-700 dark:text-rose-300"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-bold">De-identification has stopped</p>
            <p className="mt-0.5">{p.stalled_reason}</p>
          </div>
        </div>
      ) : null}

      <Card className="p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
            De-identification
          </h2>
          <span className="text-xs text-[rgb(var(--foreground-muted))]">
            updates every 10 seconds
          </span>
        </div>

        <p className="mt-2 text-2xl font-bold tabular-nums">
          {number.format(p.finished)}{' '}
          <span className="text-base font-normal text-[rgb(var(--foreground-muted))]">
            of {number.format(p.total)} files processed
          </span>{' '}
          <span className="text-base">({p.percent.toFixed(1)}%)</span>
        </p>

        <div className="mt-3">
          <Bar percent={p.percent} tone={p.stalled ? 'danger' : 'primary'} />
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-5">
          <div>
            <dt className="text-xs text-[rgb(var(--foreground-muted))]">Remaining</dt>
            <dd className="font-semibold tabular-nums">{number.format(p.remaining)}</dd>
          </div>
          <div>
            <dt className="text-xs text-[rgb(var(--foreground-muted))]">Speed</dt>
            <dd className="font-semibold tabular-nums">
              {p.per_hour > 0 ? `${number.format(p.per_hour)} / hour` : '--'}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-[rgb(var(--foreground-muted))]">Time left</dt>
            <dd className="font-semibold">
              {p.remaining === 0 ? 'done' : humanDuration(p.eta_seconds)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-[rgb(var(--foreground-muted))]">Failed</dt>
            <dd className={'font-semibold tabular-nums ' + (p.failed ? 'text-rose-600 dark:text-rose-400' : '')}>
              {number.format(p.failed)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-[rgb(var(--foreground-muted))]">Need a person</dt>
            <dd className="font-semibold tabular-nums">{number.format(p.needs_a_person)}</dd>
          </div>
        </dl>
      </Card>

      <Card className="p-5">
        <h2 className="flex items-center gap-2 text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
          <Cpu className="size-3.5" aria-hidden="true" /> Workers
        </h2>
        {p.workers.length === 0 ? (
          <p className="mt-2 text-sm text-[rgb(var(--foreground-muted))]">
            No worker has reported yet. Start one with <code>make intake-watch</code>, or the
            scheduled Job.
          </p>
        ) : (
          <ul className="mt-2">
            {p.workers.map((worker) => (
              <WorkerRow key={worker.name ?? ''} worker={worker} />
            ))}
          </ul>
        )}
      </Card>

      {batches.data && batches.data.length ? (
        <Card className="p-5">
          <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
            Pushes
          </h2>
          <ul className="mt-2 space-y-3">
            {batches.data.slice(0, 8).map((batch) => (
              <li key={batch.id}>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                  <span className="text-[rgb(var(--foreground-muted))]">
                    {batch.started_at ? new Date(batch.started_at).toLocaleString() : batch.id}
                  </span>
                  <span className="tabular-nums">
                    {number.format(batch.finished)} / {number.format(batch.total)}
                    {batch.failed ? ` · ${number.format(batch.failed)} failed` : ''}
                    {batch.needs_a_person
                      ? ` · ${number.format(batch.needs_a_person)} need a person`
                      : ''}
                  </span>
                </div>
                <div className="mt-1">
                  <Bar percent={batch.percent} />
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  )
}
