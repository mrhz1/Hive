import { AlertTriangle, CheckCircle2, Clock, FileText, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import {
  isFullyDeidentified,
  isFullyReviewed,
  type FileTally,
} from '@/schemas/applicationFile'

/**
 * One line answering "is this batch finished?".
 *
 * An application can hold a thousand documents. At that size the table
 * itself answers nothing -- a single file that failed six hours ago sits
 * on page 40 and nobody finds it by scrolling. These are the counts you
 * would otherwise have to derive by eye, and the two headline claims
 * ("all redacted", "all reviewed") are stated outright rather than left
 * for the reader to work out from them.
 */
export function FileTallyBar({ tally }: { tally: FileTally }) {
  if (tally.total === 0) return null

  const allRedacted = isFullyDeidentified(tally)
  const allReviewed = isFullyReviewed(tally)

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] px-4 py-3">
      <Stat
        icon={<FileText className="size-4" aria-hidden="true" />}
        label="documents"
        value={tally.total}
      />

      <Divider />

      {/* De-identification. The headline is the redacted count; the rest
          only appear when there is something to act on, so a finished
          application reads as one clean line. */}
      <Stat
        icon={
          allRedacted ? (
            <CheckCircle2 className="size-4" aria-hidden="true" />
          ) : (
            <FileText className="size-4" aria-hidden="true" />
          )
        }
        label="de-identified"
        value={`${tally.deidentified} of ${tally.total}`}
        tone={allRedacted ? 'success' : 'default'}
      />

      {tally.deidRunning > 0 ? (
        <Stat
          icon={<Clock className="size-4" aria-hidden="true" />}
          label="running"
          value={tally.deidRunning}
          tone="busy"
        />
      ) : null}

      {tally.deidFailed > 0 ? (
        <Stat
          icon={<AlertTriangle className="size-4" aria-hidden="true" />}
          label="failed"
          value={tally.deidFailed}
          tone="danger"
        />
      ) : null}

      {tally.deidPending > 0 ? (
        <Stat
          icon={<Clock className="size-4" aria-hidden="true" />}
          label="not started"
          value={tally.deidPending}
          tone="warning"
        />
      ) : null}

      <Divider />

      <Stat
        icon={
          allReviewed ? (
            <CheckCircle2 className="size-4" aria-hidden="true" />
          ) : (
            <Clock className="size-4" aria-hidden="true" />
          )
        }
        label="approved"
        value={`${tally.approved} of ${tally.total}`}
        tone={allReviewed && tally.rejected === 0 ? 'success' : 'default'}
      />

      {tally.rejected > 0 ? (
        <Stat
          icon={<XCircle className="size-4" aria-hidden="true" />}
          label="rejected"
          value={tally.rejected}
          tone="danger"
        />
      ) : null}

      {tally.undecided > 0 ? (
        <Stat
          icon={<Clock className="size-4" aria-hidden="true" />}
          label="undecided"
          value={tally.undecided}
          tone="warning"
        />
      ) : null}
    </div>
  )
}

// Defined in both themes (src/styles.css), so these read correctly in
// light and dark without a fallback.
const TONES = {
  default: 'text-[rgb(var(--foreground))]',
  success: 'text-[rgb(var(--success-foreground))]',
  warning: 'text-[rgb(var(--warning-foreground))]',
  danger: 'text-[rgb(var(--danger-foreground))]',
  busy: 'text-[rgb(var(--foreground-muted))]',
} as const

function Stat({
  icon,
  label,
  value,
  tone = 'default',
}: {
  icon: ReactNode
  label: string
  value: ReactNode
  tone?: keyof typeof TONES
}) {
  return (
    <div className="flex items-center gap-2">
      <span className={cn('shrink-0', TONES[tone])}>{icon}</span>
      <span className="flex items-baseline gap-1.5">
        <span className={cn('text-sm font-semibold tabular-nums', TONES[tone])}>
          {value}
        </span>
        <span className="text-xs text-[rgb(var(--foreground-muted))]">{label}</span>
      </span>
    </div>
  )
}

function Divider() {
  return (
    <span
      aria-hidden="true"
      className="hidden h-4 w-px bg-[rgb(var(--border))] sm:block"
    />
  )
}
