import { z } from 'zod'

// Mirrors the Abstraction* models in app/schemas.py.

export const abstractionCriteriaSchema = z.object({
  patient_ids: z.array(z.string()).default([]),
  modalities: z.array(z.string()).default([]),
  file_types: z.array(z.string()).default([]),
  date_from: z.string().nullable().optional(),
  date_to: z.string().nullable().optional(),
  search: z.string().nullable().optional(),
})

export type AbstractionCriteria = z.infer<typeof abstractionCriteriaSchema>

export const abstractionDocumentSchema = z.object({
  file_id: z.string(),
  application_id: z.string(),
  patient_id: z.string(),
  name: z.string(),
  file_type: z.string(),
  modality: z.string().nullable().optional(),
  document_date: z.string().nullable().optional(),
})

export type AbstractionDocument = z.infer<typeof abstractionDocumentSchema>

export const abstractionDocumentListSchema = z.array(abstractionDocumentSchema)

export const abstractionPreviewSchema = z.object({
  total: z.number(),
  patients: z.number(),
  documents: abstractionDocumentListSchema,
})

export type AbstractionPreview = z.infer<typeof abstractionPreviewSchema>

export const abstractionFolderSchema = z.object({
  id: z.string(),
  name: z.string(),
  purpose: z.string().nullable().optional(),
  owner_id: z.string().nullable().optional(),
  owner_username: z.string().nullable().optional(),
  status: z.string(),
  criteria: z.record(z.string(), z.unknown()).nullable().optional(),
  file_count: z.number().default(0),
  folder_path: z.string().nullable().optional(),
  created_at: z.string().nullable().optional(),
  expires_at: z.string().nullable().optional(),
  deleted_at: z.string().nullable().optional(),
  deleted_reason: z.string().nullable().optional(),
})

export type AbstractionFolder = z.infer<typeof abstractionFolderSchema>

export const abstractionFolderListSchema = z.array(abstractionFolderSchema)

export const regeneratedSchema = z.object({
  folder: abstractionFolderSchema,
  missing: z.number(),
})

export const FILE_TYPES = ['PDF', 'DICOM', 'DOCX'] as const

export function folderTone(status: string): 'success' | 'neutral' | 'warning' {
  if (status === 'active') return 'success'
  if (status === 'expired') return 'warning'
  return 'neutral'
}

/** Whole days until `expiresAt` (negative once past). */
export function daysLeft(
  expiresAt: string | null | undefined,
  now = Date.now()
): number | null {
  if (!expiresAt) return null
  const at = Date.parse(expiresAt)
  if (Number.isNaN(at)) return null
  return Math.ceil((at - now) / 86_400_000)
}

/** 'AA1234, bb0042 AA1234' -> ['AA1234', 'BB0042'] */
export function splitCodes(text: string): string[] {
  return [
    ...new Set(
      text
        .split(/[\s,;]+/)
        .map((code) => code.trim().toUpperCase())
        .filter(Boolean)
    ),
  ]
}
