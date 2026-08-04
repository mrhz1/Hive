import { z } from 'zod'

/**
 * Every permission the API recognises, mirroring KNOWN_PERMISSIONS in
 * app/security.py. Kept as a const tuple so `Permission` is a union of
 * literals rather than `string` -- a typo in a permission check then
 * fails at compile time instead of silently never matching.
 */
export const MODELS = ['users', 'customers', 'roles', 'logs'] as const
export const ACTIONS = ['read', 'create', 'update', 'delete'] as const

export type Model = (typeof MODELS)[number]
export type Action = (typeof ACTIONS)[number]
export type Permission = `${Model}:${Action}`

export const ALL_PERMISSIONS: Permission[] = MODELS.flatMap((model) =>
  ACTIONS.map((action) => `${model}:${action}` as Permission)
)

export const permissionSchema = z.custom<Permission>(
  (value) => typeof value === 'string' && ALL_PERMISSIONS.includes(value as Permission),
  { message: 'Unknown permission' }
)

/** Shape of the error envelope produced by app/errors.py. */
export const apiErrorSchema = z.object({
  error: z.object({
    code: z.string(),
    detail: z.string(),
    fields: z
      .array(
        z.object({ loc: z.array(z.union([z.string(), z.number()])), msg: z.string() })
      )
      .optional(),
  }),
})

export type ApiErrorBody = z.infer<typeof apiErrorSchema>

/**
 * The API emits naive ISO timestamps (no timezone suffix) because Hive
 * TIMESTAMP has no zone. Parsed leniently so a missing 'Z' does not fail
 * the whole response.
 */
export const timestampSchema = z.string().min(1)

export const idSchema = z.string().min(1)
