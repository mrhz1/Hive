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
  write_enabled: z.boolean().default(false),
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

export const remoteDatasetSchema = z.object({
  dataset: z.string(),
  connected: z.boolean(),
  project_id: z.number().nullable().optional(),
  title: z.string().nullable().optional(),
  in_production: z.boolean().nullable().optional(),
  error: z.string().nullable().optional(),
})

export type RemoteDataset = z.infer<typeof remoteDatasetSchema>

export const remoteInstrumentSchema = z.object({
  name: z.string(),
  label: z.string(),
  fields: z.number(),
  identifiers: z.number(),
  dates: z.number(),
  free_text: z.number(),
})

export type RemoteInstrument = z.infer<typeof remoteInstrumentSchema>

export const remotePreviewSchema = redcapImportSchema.extend({
  fingerprint: z.string(),
  instruments: z.array(z.string()).default([]),
  rows_in_export: z.number().default(0),
  sample_columns: z.array(z.string()).default([]),
  sample_rows: z.array(z.array(z.string())).default([]),
})

export type RemotePreview = z.infer<typeof remotePreviewSchema>

export const newRecordsPreviewSchema = z.object({
  dataset: z.string(),
  record_field: z.string(),
  count: z.number(),
  codes: z.array(z.string()),
  connected: z.boolean(),
  write_enabled: z.boolean(),
})

export type NewRecordsPreview = z.infer<typeof newRecordsPreviewSchema>

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
