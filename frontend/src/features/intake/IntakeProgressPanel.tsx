import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Cpu, Play } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { Badge, Card } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import { Can } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { useIntakeRuns, useIntakeStatus, useStartIntake } from '@/hooks/useResources'
import { queryKeys } from '@/lib/queryKeys'
import { humanDuration, type IntakeRun, type IntakeWorker } from '@/schemas/intake'

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
  const finished = !worker.alive && worker.status === 'finished'
  let dotColor = 'bg-[rgb(var(--foreground-muted))]'
  let badgeTone: 'danger' | 'success' | 'neutral' = 'neutral'
  if (!worker.alive && !finished) {
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
      <Badge tone={badgeTone}>
        {worker.alive || finished ? worker.status : 'stopped'}
      </Badge>
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

function runSummary(run: IntakeRun): string {
  let summary = `${formatNumber(run.done)} done`
  if (run.failed) summary += ` · ${formatNumber(run.failed)} failed`
  if (run.set_aside) summary += ` · ${formatNumber(run.set_aside)} excluded`
  if (run.skipped_unsettled)
    summary += ` · ${formatNumber(run.skipped_unsettled)} still being copied, run again`
  return summary
}

/** Tell whoever is watching when a run ends, not only when it starts. */
function useFinishedRunToast(active: boolean, runs: IntakeRun[] | undefined) {
  const queryClient = useQueryClient()
  const wasActive = useRef(active)
  const announced = useRef<number | null>(null)

  useEffect(() => {
    if (wasActive.current && !active) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.intake.all })
    }
    wasActive.current = active
  }, [active, queryClient])

  const latest = runs?.[0]
  useEffect(() => {
    if (!latest) return
    if (announced.current === null) {
      announced.current = latest.finished_at
      return
    }
    if (latest.finished_at <= announced.current) return
    announced.current = latest.finished_at
    toast.success('De-identification finished', { description: runSummary(latest) })
  }, [latest])
}

export function IntakeProgressPanel() {
  const { data: status, isLoading } = useIntakeStatus()
  const { data: runs } = useIntakeRuns()
  const start = useStartIntake()
  useFinishedRunToast(Boolean(status?.running || status?.starting), runs)

  if (isLoading) {
    return (
      <Card className="p-5">
        <Spinner size="md" label="Loading status" />
      </Card>
    )
  }
  if (!status) return null

  const remaining = status.remaining ?? null
  let percent = 0
  if (remaining !== null && status.done + remaining > 0) {
    percent = (status.done / (status.done + remaining)) * 100
  }

  let timeLeft = '-'
  if (status.running) timeLeft = humanDuration(status.eta_seconds)
  else if (remaining === 0) timeLeft = 'done'

  return (
    <div className="space-y-3">
      {status.stalled && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-700 dark:text-rose-300"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-bold">De-identification has stopped</p>
            <p className="mt-0.5">{status.stalled_reason}</p>
          </div>
        </div>
      )}

      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <h2 className={titleClass}>De-identification</h2>
            <Badge
              tone={status.running ? 'success' : status.starting ? 'info' : 'neutral'}
            >
              {status.running ? 'running' : status.starting ? 'starting' : 'idle'}
            </Badge>
          </div>
          <Can permission="deidentifier:run">
            <Button
              size="sm"
              disabled={status.running || status.starting}
              isLoading={start.isPending || status.starting}
              leadingIcon={<Play className="size-3.5" aria-hidden="true" />}
              onClick={() => start.mutate()}
            >
              {status.running
                ? 'Running...'
                : status.starting
                  ? 'Starting...'
                  : 'Start de-identification'}
            </Button>
          </Can>
        </div>

        {status.starting && (
          <div
            role="status"
            className="mt-3 flex items-center gap-3 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] p-3 text-sm"
          >
            <Spinner size="sm" label="" />
            <span>
              Start requested
              {status.start_requested_at
                ? ` at ${new Date(status.start_requested_at * 1000).toLocaleTimeString()}`
                : ''}
              . Waiting for a worker to pick it up, which can take a minute or two.
            </span>
          </div>
        )}

        {status.running && (
          <div className="mt-3">
            <ProgressBar percent={percent} red={status.stalled} />
          </div>
        )}

        <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-6">
          <div>
            <dt className={labelClass}>In incoming</dt>
            <dd className="font-semibold tabular-nums">
              {remaining === null ? '-' : formatNumber(remaining)}
            </dd>
          </div>
          <div>
            <dt className={labelClass}>Done this run</dt>
            <dd className="font-semibold tabular-nums">{formatNumber(status.done)}</dd>
          </div>
          <div>
            <dt className={labelClass}>Speed</dt>
            <dd className="font-semibold tabular-nums">
              {status.per_hour > 0 ? `${formatNumber(status.per_hour)} / hour` : '-'}
            </dd>
          </div>
          <div>
            <dt className={labelClass}>Time left</dt>
            <dd className="font-semibold">{timeLeft}</dd>
          </div>
          <div>
            <dt className={labelClass}>Failed</dt>
            <dd
              className={`font-semibold tabular-nums ${status.failed ? 'text-rose-600 dark:text-rose-400' : ''}`}
            >
              {formatNumber(status.failed)}
            </dd>
          </div>
          <div>
            <dt className={labelClass}>Excluded</dt>
            <dd className="font-semibold tabular-nums">
              {formatNumber(status.needs_attention)}
            </dd>
          </div>
        </dl>
      </Card>

      <Card className="p-5">
        <h2 className={`flex items-center gap-2 ${titleClass}`}>
          <Cpu className="size-3.5" aria-hidden="true" /> Workers
        </h2>
        {status.workers.length === 0 ? (
          <p className="mt-2 text-sm text-[rgb(var(--foreground-muted))]">
            No run yet. Click Start de-identification once the files are in the incoming
            folder.
          </p>
        ) : (
          <ul className="mt-2">
            {status.workers.map((worker) => (
              <WorkerRow key={worker.name ?? ''} worker={worker} />
            ))}
          </ul>
        )}
      </Card>

      {runs && runs.length > 0 && (
        <Card className="p-5">
          <h2 className={titleClass}>Last runs</h2>
          <ul className="mt-2 divide-y divide-[rgb(var(--border))] text-xs">
            {runs.slice(0, 8).map((run) => {
              const summary = runSummary(run)
              const took = humanDuration(run.finished_at - run.started_at)

              return (
                <li
                  key={`${run.host}-${run.started_at}`}
                  className="flex flex-wrap justify-between gap-2 py-2"
                >
                  <span className="text-[rgb(var(--foreground-muted))]">
                    {new Date(run.started_at * 1000).toLocaleString()} · {took}
                  </span>
                  <span className="tabular-nums">{summary}</span>
                </li>
              )
            })}
          </ul>
        </Card>
      )}
    </div>
  )
}
