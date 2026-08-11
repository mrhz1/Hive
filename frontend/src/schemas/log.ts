import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

export const AUDIT_ACTIONS = ['CREATE', 'UPDATE', 'DELETE'] as const
export type AuditAction = (typeof AUDIT_ACTIONS)[number]

export const auditLogSchema = z.object({
  id: idSchema,
  action: z.enum(AUDIT_ACTIONS),
  entity_type: z.string(),
  entity_id: z.string(),
  /** Who did it. Stored all along, but dropped here, so the page could
      not show it and could not be filtered by it. */
  user_id: z.string().nullable().optional(),
  old_values: z.record(z.string(), z.unknown()).nullable().optional(),
  new_values: z.record(z.string(), z.unknown()).nullable().optional(),
  created_at: timestampSchema,
})

export type AuditLog = z.infer<typeof auditLogSchema>

export const auditLogListSchema = z.array(auditLogSchema)

export type AuditLogFilters = {
  entity_type?: string
  entity_id?: string
  user_id?: string
  action?: string
  /** YYYY-MM-DD, both inclusive. */
  date_from?: string
  date_to?: string
  limit?: number
}
