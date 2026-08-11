import { z } from 'zod'
import { idSchema, permissionSchema, timestampSchema } from './common'

/** Mirrors app/schemas.py::User (the read model, role fields joined in). */
export const userSchema = z.object({
  id: idSchema,
  username: z.string(),
  email: z.string(),
  first_name: z.string(),
  last_name: z.string(),
  status: z.string(),
  is_active: z.boolean(),
  role_id: z.string().nullable().optional(),
  created_at: timestampSchema,
  role_name: z.string().nullable().optional(),
  permissions: z.array(permissionSchema).default([]),
})

export type User = z.infer<typeof userSchema>

export const userListSchema = z.array(userSchema)

/** 'Ada Lovelace (ada)', falling back to the username on its own. */
export function userLabel(user: User): string {
  const name = `${user.first_name ?? ''} ${user.last_name ?? ''}`.trim()
  return name ? `${name} (${user.username})` : user.username
}

export const userFormSchema = z.object({
  username: z
    .string()
    .min(1, 'Username is required')
    .max(64, 'Username must be 64 characters or fewer')
    .regex(/^[a-zA-Z0-9._-]+$/, 'Only letters, numbers, dot, underscore and hyphen'),
  email: z.string().min(1, 'Email is required').email('Enter a valid email address'),
  first_name: z.string().min(1, 'First name is required').max(64, 'Too long'),
  last_name: z.string().min(1, 'Last name is required').max(64, 'Too long'),
  status: z.string().min(1, 'Status is required'),
  is_active: z.boolean(),
  role_id: z.string().min(1, 'Role is required'),
})

export type UserFormValues = z.infer<typeof userFormSchema>

/** Self-service profile edit -- mirrors app/schemas.py::ProfileUpdate. */
export const profileFormSchema = userFormSchema.pick({
  first_name: true,
  last_name: true,
  email: true,
})

export type ProfileFormValues = z.infer<typeof profileFormSchema>

export const USER_STATUSES = ['active', 'inactive', 'suspended'] as const
