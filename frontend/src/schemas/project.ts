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

export const projectDetailSchema = projectSchema.extend({
  cohort: z.array(cohortMemberSchema).default([]),
  releases: z.array(releaseSchema).default([]),
})

export type ProjectDetail = z.infer<typeof projectDetailSchema>

export const candidateListSchema = z.array(
  z.object({ patient_id: z.string(), applications: z.number(), documents: z.number() })
)

export type Candidate = z.infer<typeof candidateListSchema>[number]

export const releaseSummarySchema = releaseSchema.extend({
  project_name: z.string().default(''),
  project_short_code: z.string().default(''),
  columns: z.record(z.string(), z.array(z.string())).default({}),
  samples: z.record(z.string(), z.array(z.record(z.string(), z.string()))).default({}),
})

export type ReleaseSummary = z.infer<typeof releaseSummarySchema>

/** A file in a release (documents.csv), to open and spot-check. */
export const releaseDocumentSchema = z.object({
  project_document_id: z.string(),
  project_patient_id: z.string(),
  file_type: z.string().default(''),
  file: z.string(),
})

export type ReleaseDocument = z.infer<typeof releaseDocumentSchema>

export const releaseDocumentListSchema = z.array(releaseDocumentSchema)

/** The letters a patient code starts with, its cohort: AVSD0012 -> AVSD. */
export function codePrefix(code: string): string {
  return /^[A-Za-z]+/.exec(code)?.[0].toUpperCase() ?? ''
}

/** Codes grouped by prefix, largest group first. */
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

/** Up to `count` documents picked at random, for a spot check. */
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
