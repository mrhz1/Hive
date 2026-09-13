import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

export const ACCESS_ACTIONS = [
  'read',
  'download',
  'export',
  'denied',
  'auth_failure',
  'integrity',
] as const

export type AccessAction = (typeof ACCESS_ACTIONS)[number]

const nullableText = z.string().nullable().optional()

export const accessLogSchema = z.object({
  id: idSchema,
  occurred_at: timestampSchema,
  action: z.string(),
  outcome: z.string(),
  actor_id: nullableText,
  actor_username: nullableText,
  actor_role: nullableText,
  source_ip: nullableText,
  user_agent: nullableText,
  request_id: nullableText,
  method: nullableText,
  path: nullableText,
  resource_type: nullableText,
  resource_id: nullableText,
  patient_id: nullableText,
  application_id: nullableText,

  identified: z.boolean().nullable().optional(),
  record_count: z.number().nullable().optional(),
  byte_count: z.number().nullable().optional(),
  detail: nullableText,
})

export type AccessLog = z.infer<typeof accessLogSchema>

export const accessLogListSchema = z.array(accessLogSchema)

export type AccessLogFilters = {
  actor_username?: string
  patient_id?: string
  action?: string
  outcome?: string
  identified_only?: boolean

  date_from?: string
  date_to?: string
  limit?: number
}

export function accessTone(
  action: string,
  outcome: string
): 'success' | 'info' | 'warning' | 'danger' | 'neutral' {
  if (outcome === 'denied') return 'warning'
  if (outcome === 'failure') return 'danger'
  if (action === 'export') return 'danger'
  if (action === 'download') return 'info'
  return 'neutral'
}

const RESOURCE_LABELS: Record<string, string> = {
  application_file: 'document',
  deidentified_file: 'de-identified document',
  file_metadata: 'document metadata',
  patient: 'patient record',
  permission: 'permission',
  file_path: 'stored file',
}

export function resourceLabel(entry: AccessLog): string {
  const type = entry.resource_type
  if (!type) return 'record'
  return RESOURCE_LABELS[type] ?? type.replace(/_/g, ' ')
}

const NAMED_RESOURCES = ['application_file', 'deidentified_file']

export function accessedName(entry: AccessLog): string | null {
  if (!entry.resource_type || !NAMED_RESOURCES.includes(entry.resource_type)) {
    return null
  }
  return entry.detail ?? null
}

export function accessSummary(entry: AccessLog): string {
  const what = resourceLabel(entry)

  if (entry.action === 'export') return `Exported ${entry.record_count ?? 0} rows`
  if (entry.action === 'download') return 'Took a copy away'
  if (entry.action === 'denied') return `Refused: needs ${entry.resource_id}`
  if (entry.action === 'auth_failure') return entry.detail ?? 'Sign-in refused'
  if (entry.action === 'integrity') return entry.detail ?? 'Integrity check failed'
  if (accessedName(entry)) return 'Opened in the viewer'
  if (entry.resource_type === 'file_metadata' && entry.detail) {

    return `Browsed ${what} (${entry.detail})`
  }
  return `Viewed a ${what}`
}
