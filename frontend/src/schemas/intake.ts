import { z } from 'zod'
import { timestampSchema } from './common'

export const INTAKE_STATUSES = [
  'queued',
  'processing',
  'done',
  'failed',
  'skipped',
  'conflict',
  'claimed',
  'submitted',
  'superseded',
] as const

export type IntakeStatus = (typeof INTAKE_STATUSES)[number]

export const intakeFileSchema = z.object({
  id: z.string(),
  batch_id: z.string(),
  source_path: z.string(),
  relative_path: z.string(),
  file_name: z.string(),
  file_extension: z.string(),
  file_size: z.number(),
  checksum: z.string().nullable().optional(),
  patient_code: z.string().nullable().optional(),
  path_code: z.string().nullable().optional(),
  name_code: z.string().nullable().optional(),
  status: z.string(),
  reason: z.string().nullable().optional(),
  detail: z.string().nullable().optional(),
  output_path: z.string().nullable().optional(),
  output_name: z.string().nullable().optional(),
  claimed_by_file_id: z.string().nullable().optional(),
  found_at: timestampSchema.nullable().optional(),
  updated_at: timestampSchema.nullable().optional(),
})

export type IntakeFile = z.infer<typeof intakeFileSchema>

export const intakeFileListSchema = z.array(intakeFileSchema)

export const intakeCountsSchema = z.object({
  total: z.number(),
  queued: z.number(),
  processing: z.number(),
  done: z.number(),
  failed: z.number(),
  skipped: z.number(),
  conflict: z.number(),
  claimed: z.number(),
  submitted: z.number(),
  superseded: z.number(),
})

export type IntakeCounts = z.infer<typeof intakeCountsSchema>

export function intakeHaystack(file: IntakeFile): string {
  return [
    file.source_path,
    file.patient_code ?? '',
    file.path_code ?? '',
    file.name_code ?? '',
    file.reason ?? '',
    file.detail ?? '',
  ]
    .join(' ')
    .toLowerCase()
}

/**
 * The list somebody hands to whoever owns the source system: one line per
 * file, full path first, then why it was refused.
 */
export function refusalReport(files: IntakeFile[]): string {
  return files
    .map((file) =>
      [file.source_path, file.reason ?? file.status, file.detail ?? '']
        .filter(Boolean)
        .join('\t')
    )
    .join('\n')
}

export const availableCodeSchema = z.object({
  code: z.string(),
  files: z.number(),
  folder: z.string(),
  patient_exists: z.boolean(),
})

export type AvailableCode = z.infer<typeof availableCodeSchema>

export const availableCodeListSchema = z.array(availableCodeSchema)

/**
 * Group a code's files by the folder they sit in, so a whole folder can be
 * taken at once. Folders are relative to the code's own folder, which is
 * what a person recognises -- the full drop path is the same on every row.
 */
export function byFolder(files: IntakeFile[]): Array<[string, IntakeFile[]]> {
  const groups = new Map<string, IntakeFile[]>()
  for (const file of files) {
    const parts = file.relative_path.split('/')
    const codeAt = parts.lastIndexOf(file.patient_code ?? '')
    const folder =
      codeAt >= 0 && codeAt < parts.length - 1
        ? parts.slice(codeAt, -1).join('/')
        : parts.slice(0, -1).join('/') || '.'
    const group = groups.get(folder) ?? []
    group.push(file)
    groups.set(folder, group)
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))
}

export const intakeWorkerSchema = z.object({
  name: z.string().nullable(),
  host: z.string().nullable().optional(),
  shards: z.array(z.number()),
  of: z.number(),
  workers: z.number(),
  status: z.string().nullable().optional(),
  alive: z.boolean(),
  last_seen: z.number(),
  seconds_since_seen: z.number(),
  current: z.array(z.string()),
  done: z.number(),
  failed: z.number(),
  per_hour: z.number(),
})

export type IntakeWorker = z.infer<typeof intakeWorkerSchema>

export const intakeProgressSchema = z.object({
  total: z.number(),
  finished: z.number(),
  done: z.number(),
  failed: z.number(),
  remaining: z.number(),
  processing: z.number(),
  needs_a_person: z.number(),
  percent: z.number(),
  per_hour: z.number(),
  eta_seconds: z.number().nullable(),
  workers: z.array(intakeWorkerSchema),
  stalled: z.boolean(),
  stalled_reason: z.string().nullable(),
  as_of: z.number(),
})

export type IntakeProgress = z.infer<typeof intakeProgressSchema>

export const intakeBatchProgressSchema = z.object({
  id: z.string(),
  root: z.string(),
  started_at: z.string().nullable().optional(),
  total: z.number(),
  finished: z.number(),
  remaining: z.number(),
  failed: z.number(),
  needs_a_person: z.number(),
  percent: z.number(),
})

export type IntakeBatchProgress = z.infer<typeof intakeBatchProgressSchema>

export const intakeBatchProgressListSchema = z.array(intakeBatchProgressSchema)

/** "3 days 4 hours", "12 minutes", "under a minute" -- the two largest units. */
export function humanDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '--'
  if (seconds < 60) return 'under a minute'
  const units: Array<[string, number]> = [
    ['day', 86400],
    ['hour', 3600],
    ['minute', 60],
  ]
  const parts: string[] = []
  let left = Math.round(seconds)
  for (const [name, size] of units) {
    const n = Math.floor(left / size)
    if (n > 0) {
      parts.push(`${n} ${name}${n === 1 ? '' : 's'}`)
      left -= n * size
    }
    if (parts.length === 2) break
  }
  return parts.join(' ')
}
