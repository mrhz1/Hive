import { z } from 'zod'

export const MODELS = [
  'user',
  'patient',
  'role',
  'application',
  'project',
  'abstraction',
] as const
export const ACTIONS = ['view', 'create', 'update', 'delete'] as const

export type Model = (typeof MODELS)[number]
export type Action = (typeof ACTIONS)[number]

export const FILES_ACTIONS = ['read', 'upload', 'download', 'delete'] as const

export const FILE_REVIEW_ACTIONS = [
  'view_original',
  'grant_original',
  'view_deidentified',
  'metadata',
  'deid_metadata',
  'reject',
] as const

export const LOG_ACTIONS = ['view', 'create'] as const

export const PROJECT_EXTRA_ACTIONS = ['workspace', 'manage'] as const

export const ABSTRACTION_EXTRA_ACTIONS = ['manage'] as const

export const REJECTION_ACTIONS = ['view'] as const

export const DEIDENTIFIER_ACTIONS = ['view', 'run', 'notify'] as const

export const ZONE2_ACTIONS = ['prepare', 'review'] as const

export const CONSENT_ACTIONS = ['view', 'update'] as const

export const SECURITY_ACTIONS = ['view', 'manage'] as const

export type FilesAction =
  (typeof FILES_ACTIONS)[number] | (typeof FILE_REVIEW_ACTIONS)[number]

export type Permission =
  | `${Model}:${Action}`
  | `files:${FilesAction}`
  | `log:${(typeof LOG_ACTIONS)[number]}`
  | `project:${(typeof PROJECT_EXTRA_ACTIONS)[number]}`
  | `abstraction:${(typeof ABSTRACTION_EXTRA_ACTIONS)[number]}`
  | `rejection:${(typeof REJECTION_ACTIONS)[number]}`
  | `deidentifier:${(typeof DEIDENTIFIER_ACTIONS)[number]}`
  | `zone2:${(typeof ZONE2_ACTIONS)[number]}`
  | `consent:${(typeof CONSENT_ACTIONS)[number]}`
  | `security:${(typeof SECURITY_ACTIONS)[number]}`

export const ALL_PERMISSIONS: Permission[] = [
  ...MODELS.flatMap((model) =>
    ACTIONS.map((action) => `${model}:${action}` as Permission)
  ),
  ...FILES_ACTIONS.map((action) => `files:${action}` as Permission),
  ...FILE_REVIEW_ACTIONS.map((action) => `files:${action}` as Permission),
  ...LOG_ACTIONS.map((action) => `log:${action}` as Permission),
  ...PROJECT_EXTRA_ACTIONS.map((action) => `project:${action}` as Permission),
  ...ABSTRACTION_EXTRA_ACTIONS.map((action) => `abstraction:${action}` as Permission),
  ...REJECTION_ACTIONS.map((action) => `rejection:${action}` as Permission),
  ...DEIDENTIFIER_ACTIONS.map((action) => `deidentifier:${action}` as Permission),
  ...ZONE2_ACTIONS.map((action) => `zone2:${action}` as Permission),
  ...CONSENT_ACTIONS.map((action) => `consent:${action}` as Permission),
  ...SECURITY_ACTIONS.map((action) => `security:${action}` as Permission),
]

export const PERMISSION_GROUPS: ReadonlyArray<{
  models: readonly string[]
  actions: readonly string[]
  rowLabel?: string
}> = [
  { models: MODELS, actions: ACTIONS },
  { models: ['files'], actions: FILES_ACTIONS },
  { models: ['files'], actions: FILE_REVIEW_ACTIONS, rowLabel: 'documents' },
  { models: ['log'], actions: LOG_ACTIONS, rowLabel: 'logs' },
  { models: ['project'], actions: PROJECT_EXTRA_ACTIONS, rowLabel: 'project access' },
  {
    models: ['abstraction'],
    actions: ABSTRACTION_EXTRA_ACTIONS,
    rowLabel: 'abstraction folders',
  },
  { models: ['rejection'], actions: REJECTION_ACTIONS, rowLabel: 'rejections' },
  {
    models: ['deidentifier'],
    actions: DEIDENTIFIER_ACTIONS,
    rowLabel: 'de-identifier',
  },
  { models: ['zone2'], actions: ZONE2_ACTIONS, rowLabel: 'zone 2' },
  { models: ['consent'], actions: CONSENT_ACTIONS, rowLabel: 'consent' },
  { models: ['security'], actions: SECURITY_ACTIONS, rowLabel: 'security' },
]

const ACTION_LABELS: Record<string, string> = {
  view_original: 'view original',
  grant_original: 'grant originals',
  workspace: 'workspace storage',
  view_deidentified: 'view de-identified',
  metadata: 'metadata',
  deid_metadata: 'de-identified metadata',
  notify: 'gets emails',
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
