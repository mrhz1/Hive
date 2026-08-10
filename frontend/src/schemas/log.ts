import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

export const AUDIT_ACTIONS = ['CREATE', 'UPDATE', 'DELETE'] as const
export type AuditAction = (typeof AUDIT_ACTIONS)[number]

export const auditLogSchema = z.object({
  id: idSchema,
  action: z.enum(AUDIT_ACTIONS),
  entity_type: z.string(),
  entity_id: z.string(),
  old_values: z.record(z.string(), z.unknown()).nullable().optional(),
  new_values: z.record(z.string(), z.unknown()).nullable().optional(),
  created_at: timestampSchema,
})

export type AuditLog = z.infer<typeof auditLogSchema>

export const auditLogListSchema = z.array(auditLogSchema)

export type AuditLogFilters = {
  entity_type?: string
  entity_id?: string
  limit?: number
}
