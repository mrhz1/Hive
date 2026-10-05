import { z } from 'zod'

export const MODELS = [
  'user',
  'patient',
  'role',
  'log',
  'application',
  'project',
] as const
export const ACTIONS = ['view', 'create', 'update', 'delete'] as const

export type Model = (typeof MODELS)[number]
export type Action = (typeof ACTIONS)[number]

export const FILES_ACTIONS = ['read', 'upload', 'download', 'delete'] as const

export const FILE_REVIEW_ACTIONS = [
  'view_original',
  'view_deidentified',
  'metadata',
  'deid_metadata',
  'reject',
] as const

export const REJECTION_ACTIONS = ['view'] as const

export const DEIDENTIFIER_ACTIONS = ['view', 'run'] as const

export const ZONE2_ACTIONS = ['prepare', 'review'] as const

export type FilesAction =
  (typeof FILES_ACTIONS)[number] | (typeof FILE_REVIEW_ACTIONS)[number]

export type Permission =
  | `${Model}:${Action}`
  | `files:${FilesAction}`
  | `rejection:${(typeof REJECTION_ACTIONS)[number]}`
  | `deidentifier:${(typeof DEIDENTIFIER_ACTIONS)[number]}`
  | `zone2:${(typeof ZONE2_ACTIONS)[number]}`

export const ALL_PERMISSIONS: Permission[] = [
  ...MODELS.flatMap((model) =>
    ACTIONS.map((action) => `${model}:${action}` as Permission)
  ),
  ...FILES_ACTIONS.map((action) => `files:${action}` as Permission),
  ...FILE_REVIEW_ACTIONS.map((action) => `files:${action}` as Permission),
  ...REJECTION_ACTIONS.map((action) => `rejection:${action}` as Permission),
  ...DEIDENTIFIER_ACTIONS.map((action) => `deidentifier:${action}` as Permission),
  ...ZONE2_ACTIONS.map((action) => `zone2:${action}` as Permission),
]

export const PERMISSION_GROUPS: ReadonlyArray<{
  models: readonly string[]
  actions: readonly string[]
  rowLabel?: string
}> = [
  { models: MODELS, actions: ACTIONS },
  { models: ['files'], actions: FILES_ACTIONS },
  { models: ['files'], actions: FILE_REVIEW_ACTIONS, rowLabel: 'documents' },
  { models: ['rejection'], actions: REJECTION_ACTIONS, rowLabel: 'rejections' },
  {
    models: ['deidentifier'],
    actions: DEIDENTIFIER_ACTIONS,
    rowLabel: 'de-identifier',
  },
  { models: ['zone2'], actions: ZONE2_ACTIONS, rowLabel: 'zone 2' },
]

const ACTION_LABELS: Record<string, string> = {
  view_original: 'view original',
  view_deidentified: 'view de-identified',
  metadata: 'metadata',
  deid_metadata: 'de-identified metadata',
}

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action
}

export const permissionSchema = z.custom<Permission>(
  (value) => typeof value === 'string' && ALL_PERMISSIONS.includes(value as Permission),
  { message: 'Unknown permission' }
)

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
