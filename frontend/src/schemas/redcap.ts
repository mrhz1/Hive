import { z } from 'zod'

export const REDCAP_KINDS = ['dictionary', 'records', 'log'] as const
export type RedcapKind = (typeof REDCAP_KINDS)[number]

export const REDCAP_KIND_LABELS: Record<RedcapKind, string> = {
  dictionary: 'Data dictionary',
  records: 'Records (data)',
  log: 'Logging (audit trail)',
}

export const redcapDatasetSchema = z.object({
  dataset: z.string(),
  fields: z.number(),
  patients: z.number(),
  values: z.number(),
  log_entries: z.number(),
  last_import: z.string().nullable().optional(),
})

export type RedcapDataset = z.infer<typeof redcapDatasetSchema>

export const redcapStatusSchema = z.object({
  mode: z.string(),
  datasets: z.array(redcapDatasetSchema),
})

export const redcapImportSchema = z.object({
  dataset: z.string(),
  kind: z.string(),
  applied: z.boolean(),
  counts: z.record(z.string(), z.number()),
  problems: z.array(z.string()).default([]),
  notes: z.array(z.string()).default([]),
})

export type RedcapImport = z.infer<typeof redcapImportSchema>

export const followupRowSchema = z.object({
  patient_id: z.string(),
  first_name: z.string().nullable().optional(),
  email: z.string().nullable().optional(),
  consent_version: z.string().nullable().optional(),
  consent_update: z.string().nullable().optional(),
  reasons: z.array(z.string()).default([]),
})

export const followupSummarySchema = z.object({
  automated: z.number(),
  manual: z.number(),
  not_contacted: z.number(),
  sample: z.array(followupRowSchema),
})

export type FollowupSummary = z.infer<typeof followupSummarySchema>
