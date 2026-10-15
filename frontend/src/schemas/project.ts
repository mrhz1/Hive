import { z } from 'zod'

const nullableText = z.string().nullable().optional()

export const PROJECT_STATUS_LABELS: Record<string, string> = {
  draft: 'draft',
  in_review: 'waiting for review',
  released: 'released',
  rejected: 'sent back',
  ended: 'ended',
}

export const projectSchema = z.object({
  id: z.string(),
  short_code: z.string(),
  name: z.string(),
  description: nullableText,
  approval_reference: nullableText,
  consent_confirmed: z.boolean(),
  documents_approved: z.boolean(),
  status: z.string(),
  status_reason: nullableText,
  created_by_id: nullableText,
  created_at: nullableText,
  updated_at: nullableText,

  workspace_path: nullableText,
  workspace_built_at: nullableText,
  workspace_expires_at: nullableText,
})

export type Project = z.infer<typeof projectSchema>

export const projectListSchema = z.array(projectSchema)

export const releaseSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  status: z.string(),
  status_reason: nullableText,
  prepared_by_id: nullableText,
  prepared_at: nullableText,
  reviewed_by_id: nullableText,
  reviewed_at: nullableText,
  patients: z.number(),
  applications: z.number(),
  documents: z.number(),
  files_included: z.boolean(),
  archive_path: nullableText,
  inbox_path: nullableText,
  release_path: nullableText,
})

export type Release = z.infer<typeof releaseSchema>

export const cohortMemberSchema = z.object({
  patient_id: z.string(),
  project_patient_id: z.string(),
  applications: z.number(),
  documents: z.number(),
})

export const projectMemberSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  username: nullableText,
  added_at: nullableText,
})

export type ProjectMember = z.infer<typeof projectMemberSchema>

export const projectDetailSchema = projectSchema.extend({
  cohort: z.array(cohortMemberSchema).default([]),
  releases: z.array(releaseSchema).default([]),
  members: z.array(projectMemberSchema).default([]),
})

export type ProjectDetail = z.infer<typeof projectDetailSchema>

export const candidateListSchema = z.array(
  z.object({
    patient_id: z.string(),
    applications: z.number(),
    documents: z.number(),

    excluded_reason: nullableText,
  })
)

export type Candidate = z.infer<typeof candidateListSchema>[number]

export const releaseSummarySchema = releaseSchema.extend({
  project_name: z.string().default(''),
  project_short_code: z.string().default(''),
  columns: z.record(z.string(), z.array(z.string())).default({}),
  samples: z.record(z.string(), z.array(z.record(z.string(), z.string()))).default({}),
})

export type ReleaseSummary = z.infer<typeof releaseSummarySchema>

export const releaseDocumentSchema = z.object({
  project_document_id: z.string(),
  project_patient_id: z.string(),
  file_type: z.string().default(''),
  file: z.string(),
})

export type ReleaseDocument = z.infer<typeof releaseDocumentSchema>

export const releaseDocumentListSchema = z.array(releaseDocumentSchema)

export function codePrefix(code: string): string {
  return /^[A-Za-z]+/.exec(code)?.[0].toUpperCase() ?? ''
}

export function groupByPrefix(codes: readonly string[]): Array<[string, string[]]> {
  const groups = new Map<string, string[]>()
  for (const code of codes) {
    const prefix = codePrefix(code)
    if (!prefix) continue
    groups.set(prefix, [...(groups.get(prefix) ?? []), code])
  }
  return [...groups.entries()].sort(
    (a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0])
  )
}

export function randomSample<T>(
  items: readonly T[],
  count: number,
  random = Math.random
): T[] {
  const pool = [...items]
  for (let i = pool.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1))
    ;[pool[i], pool[j]] = [pool[j] as T, pool[i] as T]
  }
  return pool.slice(0, count)
}

export const releaseSummaryListSchema = z.array(releaseSummarySchema)

export type ProjectPayload = {
  name?: string
  description?: string | null
  approval_reference?: string | null
  consent_confirmed?: boolean
  documents_approved?: boolean
}

export function projectTone(status: string): 'neutral' | 'info' | 'success' | 'danger' {
  if (status === 'released') return 'success'
  if (status === 'rejected') return 'danger'
  if (status === 'in_review') return 'info'
  return 'neutral'
}

export function releaseTone(status: string): 'info' | 'success' | 'danger' | 'neutral' {
  if (status === 'approved') return 'success'
  if (status === 'rejected') return 'danger'
  if (status === 'in_review') return 'info'
  return 'neutral'
}

export type CohortCriteria = {
  prefixes?: string[]
  registered_from?: string | null
  registered_to?: string | null
  age_min?: number | null
  age_max?: number | null
  countries?: string[]
  states?: string[]
  institution_codes?: string[]
  alive_only?: boolean
  modalities?: string[]
  document_from?: string | null
  document_to?: string | null
  exclude_codes?: string[]
}

export const cohortSearchSchema = z.object({
  matches: z.array(z.string()),
  excluded: z.record(z.string(), z.string()).default({}),
})

export type CohortSearchResult = z.infer<typeof cohortSearchSchema>

export const CONSENT_TYPES = ['research', 'documents'] as const
export const CONSENT_STATUSES = ['granted', 'refused', 'withdrawn'] as const

export const CONSENT_TYPE_LABELS: Record<string, string> = {
  research: 'Research use of data',
  documents: 'PDFs and images',
}

export const consentSchema = z.object({
  id: z.string(),
  patient_id: z.string(),
  consent_type: z.string(),
  status: z.string(),
  version: nullableText,
  consent_date: nullableText,
  note: nullableText,
  source: nullableText,
  recorded_by_id: nullableText,
  recorded_at: nullableText,
})

export type Consent = z.infer<typeof consentSchema>

export const consentListSchema = z.array(consentSchema)

export type ConsentPayload = {
  patient_id: string
  consent_type: string
  status: string
  version?: string | null
  consent_date?: string | null
  note?: string | null
}

export const consentImportSchema = z.object({
  applied: z.boolean().default(false),
  counts: z.record(z.string(), z.number()),
  rows: z.array(
    z.object({
      line: z.number(),
      code: z.string().default(''),
      consent_type: z.string().default(''),
      status: z.string().default(''),
      action: z.enum(['add', 'unchanged', 'error']),
      errors: z.array(z.string()).default([]),
    })
  ),
})

export type ConsentImportResult = z.infer<typeof consentImportSchema>

export function consentTone(status: string) {
  if (status === 'granted') return 'success' as const
  if (status === 'refused' || status === 'withdrawn') return 'danger' as const
  return 'neutral' as const
}
