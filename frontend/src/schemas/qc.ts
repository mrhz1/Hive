import { z } from 'zod'

export const qcRuleSchema = z.object({
  code: z.string(),
  severity: z.string(),
  text: z.string(),
})

export const qcRunSchema = z.object({
  name: z.string(),
  made_at: z.string(),
  run_by: z.string().default(''),
  issues: z.number().nullable().default(null),
  high: z.number().nullable().default(null),
  suppressed: z.number().nullable().default(null),
  stale_suppressions: z.number().default(0),
  rules: z.record(z.string(), z.number()).default({}),
  cohorts: z
    .record(z.string(), z.object({ issues: z.number(), high: z.number() }))
    .default({}),
})

export const qcStateSchema = z.object({
  running: z.boolean(),
  started_at: z.string().nullable().default(null),
  run_by: z.string().nullable().default(null),
  error: z.string().nullable().default(null),
})

export const qcOverviewSchema = z.object({
  state: qcStateSchema,
  rules: z.array(qcRuleSchema),
  runs: z.array(qcRunSchema),
})

export const qcIssuesSchema = z.object({
  columns: z.array(z.string()),
  rows: z.array(z.array(z.string())),
  total: z.number(),
  page: z.number(),
  size: z.number(),
})

export const qcSuppressionSchema = z.object({
  rule: z.string(),
  record: z.string(),
  reason: z.string().default(''),
  by: z.string().default(''),
  date: z.string().default(''),
})

export type QcRule = z.infer<typeof qcRuleSchema>
export type QcRun = z.infer<typeof qcRunSchema>
export type QcOverview = z.infer<typeof qcOverviewSchema>
export type QcIssues = z.infer<typeof qcIssuesSchema>
export type QcSuppression = z.infer<typeof qcSuppressionSchema>

export const institutionSchema = z.object({
  code: z.string(),
  name: z.string().nullable().default(null),
  contact_email: z.string().nullable().default(null),
  patients: z.number().default(0),
  updated_by_id: z.string().nullable().default(null),
  updated_at: z.string().nullable().default(null),
})

export type Institution = z.infer<typeof institutionSchema>

const withdrawalProjectSchema = z.object({
  id: z.string(),
  short_code: z.string(),
  name: z.string(),
  status: z.string(),
  ended: z.boolean(),
  project_patient_id: z.string(),
  cohort_size: z.number(),
  workspace: z.boolean(),
  pending_releases: z.array(z.string()),
  released: z.array(z.string()),
})

export const withdrawalPreviewSchema = z.object({
  patient_id: z.string(),
  consent_status: z.string().nullable(),
  consent_date: z.string().nullable(),
  allowed: z.boolean(),
  blocked_reason: z.string().nullable(),
  applications: z.array(
    z.object({ id: z.string(), status: z.string(), documents: z.number() })
  ),
  documents: z.number(),
  problem_files: z.record(z.string(), z.number()),
  redcap_values: z.number(),
  projects: z.array(withdrawalProjectSchema),
  abstraction_folders: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      documents: z.number(),
      total: z.number(),
    })
  ),
})

export const withdrawalResultSchema = z.object({
  patient_id: z.string(),
  documents: z.number(),
  applications: z.number(),
  problem_files: z.number(),
  redcap_values: z.number(),
  projects: z.array(
    z.object({
      short_code: z.string(),
      workspace: z.string().nullable(),
      releases_rejected: z.number(),
    })
  ),
  abstraction_folders: z.array(z.object({ name: z.string(), result: z.string() })),
  already_released: z.array(
    z.object({ short_code: z.string(), releases: z.array(z.string()) })
  ),
})

export type WithdrawalPreview = z.infer<typeof withdrawalPreviewSchema>
export type WithdrawalResult = z.infer<typeof withdrawalResultSchema>
