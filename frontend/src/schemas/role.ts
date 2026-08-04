import { z } from 'zod'
import { ALL_PERMISSIONS, idSchema, permissionSchema } from './common'

/** Mirrors app/schemas.py::Role. */
export const roleSchema = z.object({
  id: idSchema,
  name: z.string(),
  permissions: z.array(permissionSchema).default([]),
})

export type Role = z.infer<typeof roleSchema>

export const roleListSchema = z.array(roleSchema)

export const roleFormSchema = z.object({
  name: z
    .string()
    .min(1, 'Name is required')
    .max(64, 'Name must be 64 characters or fewer'),
  // The API rejects unknown grants with a 422, so the same closed set is
  // enforced here to catch it before a round trip.
  permissions: z
    .array(permissionSchema)
    .refine((values) => values.every((v) => ALL_PERMISSIONS.includes(v)), {
      message: 'Contains an unknown permission',
    }),
})

export type RoleFormValues = z.infer<typeof roleFormSchema>
