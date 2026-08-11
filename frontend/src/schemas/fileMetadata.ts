import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

/**
 * A row of the metadata browser: what was extracted from a document,
 * plus enough about the document itself to recognise it.
 *
 * Extracted values arrive as strings -- app/file_metadata.py stringifies
 * whatever the format handed it -- but nothing here depends on that, so
 * the record stays permissive rather than rejecting a whole page over one
 * odd field.
 */
export const fileMetadataRowSchema = z.object({
  id: idSchema,
  file_id: idSchema,
  file_type: z.string(),
  metadata: z.record(z.string(), z.unknown()).default({}),
  status: z.string(),
  error: z.string().nullable().optional(),
  created_at: timestampSchema,
  file_name: z.string().nullable().optional(),
  application_id: z.string().nullable().optional(),
  patient_id: z.string().nullable().optional(),
})

export type FileMetadataRow = z.infer<typeof fileMetadataRowSchema>

export const fileMetadataRowListSchema = z.array(fileMetadataRowSchema)

export type FileMetadataFilters = {
  search?: string
  status?: string
  file_type?: string
  patient_id?: string
}

/** Drops the empty filters, so the query key and the URL stay tidy. */
export function activeFilters(
  filters: FileMetadataFilters
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(filters).filter(([, value]) => Boolean(value?.trim()))
  ) as Record<string, string>
}

export function metadataEntries(
  row: FileMetadataRow
): Array<[string, string]> {
  return Object.entries(row.metadata)
    .map(([key, value]) => [key, value == null ? '' : String(value)] as [string, string])
    .sort((a, b) => a[0].localeCompare(b[0]))
}

/** A one-line taste of the blob, for the table cell. */
export function metadataPreview(row: FileMetadataRow, limit = 3): string {
  const entries = metadataEntries(row).filter(([, value]) => value !== '')
  if (entries.length === 0) return 'No fields extracted'

  const shown = entries
    .slice(0, limit)
    .map(([key, value]) => `${key}: ${value}`)
    .join(' · ')

  return entries.length > limit
    ? `${shown} · +${entries.length - limit} more`
    : shown
}

export function metadataFieldCount(row: FileMetadataRow): number {
  return Object.keys(row.metadata).length
}
