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
