import { z } from 'zod'

export const MODELS = ['user', 'patient', 'role', 'log', 'application'] as const
export const ACTIONS = ['view', 'create', 'update', 'delete'] as const

export type Model = (typeof MODELS)[number]
export type Action = (typeof ACTIONS)[number]

export const FILES_ACTIONS = ['read', 'upload', 'download', 'delete'] as const
export type FilesAction = (typeof FILES_ACTIONS)[number]

export type Permission = `${Model}:${Action}` | `files:${FilesAction}`

export const ALL_PERMISSIONS: Permission[] = [
  ...MODELS.flatMap((model) =>
    ACTIONS.map((action) => `${model}:${action}` as Permission)
  ),
  ...FILES_ACTIONS.map((action) => `files:${action}` as Permission),
]

/**
 * How the role editor lays the grants out.
 *
 * Two groups, because `files` takes different action names and putting
 * read/upload/download under headers saying view/create/update would be
 * actively wrong. Anything added here appears in the editor
 * automatically -- a permission the API knows about but this does not
 * is one nobody can grant, which is how the Files section shipped
 * invisible.
 */
export const PERMISSION_GROUPS: ReadonlyArray<{
  models: readonly string[]
  actions: readonly string[]
}> = [
  { models: MODELS, actions: ACTIONS },
  { models: ['files'], actions: FILES_ACTIONS },
]

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

export const timestampSchema = z.string().min(1)

export const idSchema = z.string().min(1)
