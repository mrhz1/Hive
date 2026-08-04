import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

/** Mirrors app/schemas.py::Customer. */
export const customerSchema = z.object({
  id: idSchema,
  email: z.string(),
  first_name: z.string(),
  last_name: z.string(),
  phone_number: z.string(),
  address: z.string().nullable().optional(),
  status: z.string(),
  is_active: z.boolean(),
  created_at: timestampSchema,
})

export type Customer = z.infer<typeof customerSchema>

export const customerListSchema = z.array(customerSchema)

export const customerFormSchema = z.object({
  email: z.string().min(1, 'Email is required').email('Enter a valid email address'),
  first_name: z.string().min(1, 'First name is required').max(64, 'Too long'),
  last_name: z.string().min(1, 'Last name is required').max(64, 'Too long'),
  phone_number: z
    .string()
    .min(1, 'Phone number is required')
    // Deliberately permissive: the API stores phone as an opaque STRING
    // and enforces uniqueness on it, so over-validating here would reject
    // legitimate international formats the backend accepts.
    .regex(/^[+()\d\s-]+$/, 'Digits, spaces and + ( ) - only')
    .max(32, 'Too long'),
  address: z.string().max(256, 'Too long'),
  status: z.string().min(1, 'Status is required'),
  is_active: z.boolean(),
})

export type CustomerFormValues = z.infer<typeof customerFormSchema>

export const CUSTOMER_STATUSES = ['active', 'inactive', 'vip', 'suspended'] as const
