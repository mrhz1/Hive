import { z } from 'zod'

export const problemFileSchema = z.object({
  path: z.string(),
  file_name: z.string(),
  full_path: z.string(),
  reason: z.string().nullable().optional(),
  detail: z.string().nullable().optional(),
  path_code: z.string().nullable().optional(),
  name_code: z.string().nullable().optional(),
  file_extension: z.string(),
  file_size: z.number(),
  moved_at: z.number().nullable().optional(),
})

export type ProblemFile = z.infer<typeof problemFileSchema>

export const problemFileListSchema = z.array(problemFileSchema)

export type ProblemList = 'failed' | 'attention'

export const redactedFileSchema = z.object({
  id: z.string(),
  patient_code: z.string(),
  output_name: z.string(),
  file_name: z.string(),
  relative_path: z.string(),
  file_extension: z.string(),
  file_size: z.number(),
  method: z.string().nullable().optional(),
})

export type RedactedFile = z.infer<typeof redactedFileSchema>

export const redactedFileListSchema = z.array(redactedFileSchema)

export const availableCodeSchema = z.object({
  code: z.string(),
  files: z.number(),
  folder: z.string(),
  patient_exists: z.boolean(),
})

export type AvailableCode = z.infer<typeof availableCodeSchema>

export const availableCodeListSchema = z.array(availableCodeSchema)

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

export const intakeStatusSchema = z.object({
  running: z.boolean(),
  remaining: z.number().nullable().optional(),
  remaining_counted_at: z.number().nullable().optional(),
  done: z.number(),
  failed: z.number(),
  needs_attention: z.number(),
  per_hour: z.number(),
  eta_seconds: z.number().nullable(),
  workers: z.array(intakeWorkerSchema),
  stalled: z.boolean(),
  stalled_reason: z.string().nullable(),
  as_of: z.number(),
})

export type IntakeStatus = z.infer<typeof intakeStatusSchema>

export const intakeRunSchema = z.object({
  outcome: z.string(),
  done: z.number(),
  failed: z.number(),
  set_aside: z.number(),
  skipped_unsettled: z.number(),
  workers: z.number(),
  host: z.string(),
  started_at: z.number(),
  finished_at: z.number(),
})

export type IntakeRun = z.infer<typeof intakeRunSchema>

export const intakeRunListSchema = z.array(intakeRunSchema)

export function problemSearchText(file: ProblemFile): string {
  const values = [
    file.full_path,
    file.path_code,
    file.name_code,
    file.reason,
    file.detail,
  ]
  return values.filter(Boolean).join(' ').toLowerCase()
}

export function filesToText(files: ProblemFile[]): string {
  const lines = files.map((file) => {
    const parts = [file.full_path, file.reason ?? '']
    if (file.detail) parts.push(file.detail)
    return parts.join('\t')
  })
  return lines.join('\n')
}

export function groupByFolder(files: RedactedFile[]): [string, RedactedFile[]][] {
  const groups: Record<string, RedactedFile[]> = {}
  for (const file of files) {
    const parts = file.relative_path.split('/')
    const folder = parts.slice(0, -1).join('/') || '.'
    const group = groups[folder] ?? []
    group.push(file)
    groups[folder] = group
  }
  return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]))
}

export function humanDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '--'
  if (seconds < 60) return 'under a minute'

  const total = Math.round(seconds)
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)

  const parts = []
  if (days) parts.push(`${days} day${days === 1 ? '' : 's'}`)
  if (hours) parts.push(`${hours} hour${hours === 1 ? '' : 's'}`)
  if (minutes) parts.push(`${minutes} minute${minutes === 1 ? '' : 's'}`)
  return parts.slice(0, 2).join(' ')
}
