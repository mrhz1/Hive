/**
 * How hard the file table is allowed to poll while de-identification runs.
 *
 * Two separate pollers, because they answer different questions and cost
 * different amounts:
 *
 *   - progress: "how far into this document are we" -- the API reads a
 *     small file off shared storage, no database involved.
 *   - list:     "is it finished yet" -- a Hive query, and the only thing
 *     it is waiting for is a status flipping to done at the very end.
 *
 * Both are gated on something actually running, so an idle application
 * polls nothing at all. These knobs are for tuning the cost while it is.
 *
 * Build-time, like every other VITE_ variable: the values are compiled
 * into the bundle, so changing .env means rebuilding the frontend. There
 * is no runtime switch -- see DEPLOYMENT.md.
 */

/** Below this a poll is more expensive than the thing it is watching. */
const MIN_POLL_MS = 1000

/** A page of OCR takes 20-30s, so this is already far finer than needed. */
const DEFAULT_PROGRESS_POLL_MS = 5000

/** Only the final status flip is waited on here, so it can be lazy. */
const DEFAULT_LIST_REFRESH_MS = 15000

function readBool(raw: string | undefined, fallback: boolean): boolean {
  if (raw === undefined || raw.trim() === '') return fallback
  return ['1', 'true', 'yes', 'on'].includes(raw.trim().toLowerCase())
}

/**
 * A millisecond interval, or `false` for "do not poll".
 *
 * `0` and `off` disable the poller outright. Anything positive but
 * absurdly small is raised to MIN_POLL_MS rather than honoured: the
 * variable exists to spare the API, and a typo'd `50` would do the
 * opposite of what whoever set it intended.
 */
function readInterval(
  raw: string | undefined,
  fallback: number,
  label: string
): number | false {
  if (raw === undefined || raw.trim() === '') return fallback

  const value = raw.trim().toLowerCase()
  if (value === '0' || value === 'off' || value === 'false') return false

  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed < 0) {
    console.warn(`[hive] ${label}=${raw} is not a number; using ${fallback}ms`)
    return fallback
  }

  if (parsed < MIN_POLL_MS) {
    console.warn(
      `[hive] ${label}=${raw} is below the ${MIN_POLL_MS}ms floor; using ${MIN_POLL_MS}ms. ` +
        `Set it to 0 to turn the poller off instead.`
    )
    return MIN_POLL_MS
  }

  return parsed
}

/** Whether to show live page counts at all. */
export const DEID_PROGRESS_ENABLED = readBool(
  import.meta.env.VITE_DEID_PROGRESS_ENABLED,
  true
)

export const DEID_PROGRESS_POLL_MS = readInterval(
  import.meta.env.VITE_DEID_PROGRESS_POLL_MS,
  DEFAULT_PROGRESS_POLL_MS,
  'VITE_DEID_PROGRESS_POLL_MS'
)

export const DEID_LIST_REFRESH_MS = readInterval(
  import.meta.env.VITE_DEID_LIST_REFRESH_MS,
  DEFAULT_LIST_REFRESH_MS,
  'VITE_DEID_LIST_REFRESH_MS'
)

/**
 * Whether the progress poller should run.
 *
 * Disabled by the flag, or by setting its interval to 0 -- both mean the
 * same thing to the caller, and having one place decide it keeps the
 * hook from having to know about both.
 */
export function progressPollingEnabled(): boolean {
  return DEID_PROGRESS_ENABLED && DEID_PROGRESS_POLL_MS !== false
}
