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

export type PermissionGroup = {
  models: readonly string[]
  actions: readonly string[]
  rowLabel?: string
  labels?: Readonly<Record<string, string>>
}

export type PermissionSection = {
  id: 'zone1' | 'zone1x' | 'zone2' | 'admin'
  description: string
  groups: readonly PermissionGroup[]
}

export const PERMISSION_SECTIONS: readonly PermissionSection[] = [
  {
    id: 'zone1',
    description: 'Intake, cleaning, review and the archive. Real names are allowed here.',
    groups: [
      { models: ['patient', 'application'], actions: ACTIONS },
      { models: ['files'], actions: FILES_ACTIONS },
      { models: ['files'], actions: FILE_REVIEW_ACTIONS, rowLabel: 'documents' },
      { models: ['rejection'], actions: REJECTION_ACTIONS, rowLabel: 'rejections' },
      {
        models: ['deidentifier'],
        actions: DEIDENTIFIER_ACTIONS,
        rowLabel: 'de-identifier',
      },
    ],
  },
  {
    id: 'zone1x',
    description: 'Preparing data for one project: consent, cohorts, workspaces, folders.',
    groups: [
      { models: ['consent'], actions: CONSENT_ACTIONS, rowLabel: 'consent matrix' },
      {
        models: ['project'],
        actions: [...ACTIONS, ...PROJECT_EXTRA_ACTIONS],
        rowLabel: 'projects',
        labels: { workspace: 'workspace storage', manage: 'all projects + members' },
      },
      {
        models: ['abstraction'],
        actions: [...ACTIONS, ...ABSTRACTION_EXTRA_ACTIONS],
        rowLabel: 'abstraction folders',
        labels: { manage: 'everyone’s folders' },
      },
    ],
  },
  {
    id: 'zone2',
    description: 'Checking a safe copy and releasing it to researchers.',
    groups: [{ models: ['zone2'], actions: ZONE2_ACTIONS, rowLabel: 'zone 2 release' }],
  },
  {
    id: 'admin',
    description: 'People, roles, logs and security.',
    groups: [
      { models: ['user', 'role'], actions: ACTIONS },
      { models: ['log'], actions: LOG_ACTIONS, rowLabel: 'logs' },
      { models: ['security'], actions: SECURITY_ACTIONS },
    ],
  },
]

const ACTION_LABELS: Record<string, string> = {
  view_original: 'view original',
  grant_original: 'grant originals',
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
