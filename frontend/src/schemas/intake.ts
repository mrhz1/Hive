import { z } from 'zod'
import { timestampSchema } from './common'

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

export function intakeSearchText(file: IntakeFile): string {
  const values = [
    file.source_path,
    file.patient_code,
    file.path_code,
    file.name_code,
    file.reason,
    file.detail,
  ]
  return values.filter(Boolean).join(' ').toLowerCase()
}

export function filesToText(files: IntakeFile[]): string {
  const lines = files.map((file) => {
    const parts = [file.source_path, file.reason ?? file.status]
    if (file.detail) parts.push(file.detail)
    return parts.join('\t')
  })
  return lines.join('\n')
}

export const availableCodeSchema = z.object({
  code: z.string(),
  files: z.number(),
  folder: z.string(),
  patient_exists: z.boolean(),
})

export type AvailableCode = z.infer<typeof availableCodeSchema>

export const availableCodeListSchema = z.array(availableCodeSchema)

export function groupByFolder(files: IntakeFile[]): [string, IntakeFile[]][] {
  const groups: Record<string, IntakeFile[]> = {}
  for (const file of files) {
    const parts = file.relative_path.split('/')
    const codeIndex = parts.lastIndexOf(file.patient_code ?? '')
    let folder
    if (codeIndex >= 0 && codeIndex < parts.length - 1) {
      folder = parts.slice(codeIndex, -1).join('/')
    } else {
      folder = parts.slice(0, -1).join('/') || '.'
    }
    const group = groups[folder] ?? []
    group.push(file)
    groups[folder] = group
  }
  return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]))
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
