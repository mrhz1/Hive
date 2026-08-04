import { describe, expect, it } from 'vitest'
import { ApiError, toApiError } from '@/lib/api/client'
import { ALL_PERMISSIONS } from '@/schemas/common'
import { userFormSchema } from '@/schemas/user'
import { customerFormSchema } from '@/schemas/customer'
import { roleFormSchema } from '@/schemas/role'

describe('permissions', () => {
  it('enumerates exactly the 16 grants the API recognises', () => {
    expect(ALL_PERMISSIONS).toHaveLength(16)
    expect(ALL_PERMISSIONS).toContain('users:read')
    expect(ALL_PERMISSIONS).toContain('logs:delete')
  })
})

describe('userFormSchema', () => {
  const valid = {
    username: 'jdoe',
    email: 'jdoe@example.com',
    first_name: 'Jane',
    last_name: 'Doe',
    status: 'active',
    is_active: true,
    role_id: 'role-viewer',
  }

  it('accepts a valid user', () => {
    expect(userFormSchema.safeParse(valid).success).toBe(true)
  })

  it('requires a role -- every user must have one', () => {
    const result = userFormSchema.safeParse({ ...valid, role_id: '' })
    expect(result.success).toBe(false)
    if (!result.success) {
      const issue = result.error.issues.find((i) => i.path[0] === 'role_id')
      expect(issue?.message).toBe('Role is required')
    }
  })

  it('rejects a malformed email with a message for the field', () => {
    const result = userFormSchema.safeParse({ ...valid, email: 'not-an-email' })
    expect(result.success).toBe(false)
    if (!result.success) {
      const issue = result.error.issues.find((i) => i.path[0] === 'email')
      expect(issue?.message).toBe('Enter a valid email address')
    }
  })

  it('rejects a username with characters the API would not accept', () => {
    expect(userFormSchema.safeParse({ ...valid, username: 'has space' }).success).toBe(
      false
    )
  })

  it('requires a first name', () => {
    const result = userFormSchema.safeParse({ ...valid, first_name: '' })
    expect(result.success).toBe(false)
  })
})

describe('customerFormSchema', () => {
  const valid = {
    email: 'acme@example.com',
    first_name: 'Acme',
    last_name: 'Corp',
    phone_number: '+1 555 010 0100',
    address: '',
    status: 'active',
    is_active: true,
  }

  it('accepts international phone formats', () => {
    expect(customerFormSchema.safeParse(valid).success).toBe(true)
    expect(
      customerFormSchema.safeParse({ ...valid, phone_number: '(415) 555-0182' }).success
    ).toBe(true)
  })

  it('rejects a phone number containing letters', () => {
    expect(
      customerFormSchema.safeParse({ ...valid, phone_number: 'call-me' }).success
    ).toBe(false)
  })

  it('treats address as optional', () => {
    expect(customerFormSchema.safeParse({ ...valid, address: '' }).success).toBe(true)
  })
})

describe('roleFormSchema', () => {
  it('accepts known permissions', () => {
    const result = roleFormSchema.safeParse({
      name: 'support',
      permissions: ['users:read', 'customers:update'],
    })
    expect(result.success).toBe(true)
  })

  it('rejects an unknown permission before it reaches the API', () => {
    const result = roleFormSchema.safeParse({
      name: 'support',
      permissions: ['user:red'],
    })
    expect(result.success).toBe(false)
  })

  it('allows a role with no permissions', () => {
    expect(roleFormSchema.safeParse({ name: 'empty', permissions: [] }).success).toBe(
      true
    )
  })
})

describe('toApiError', () => {
  it('maps the API error envelope onto ApiError', () => {
    const error = toApiError({
      isAxiosError: true,
      message: 'Request failed',
      response: {
        status: 409,
        data: { error: { code: 'conflict', detail: "Username 'jdoe' already exists" } },
      },
    })

    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(409)
    expect(error.isConflict).toBe(true)
    expect(error.message).toBe("Username 'jdoe' already exists")
  })

  it('extracts per-field messages from a 422', () => {
    const error = toApiError({
      isAxiosError: true,
      message: 'Request failed',
      response: {
        status: 422,
        data: {
          error: {
            code: 'validation_error',
            detail: 'Request body failed validation',
            fields: [
              { loc: ['body', 'email'], msg: 'value is not a valid email address' },
            ],
          },
        },
      },
    })

    expect(error.fieldErrors).toEqual([
      { field: 'email', message: 'value is not a valid email address' },
    ])
  })

  it('reports an unreachable API rather than a bare axios message', () => {
    const error = toApiError({ isAxiosError: true, message: 'Network Error' })
    expect(error.status).toBe(0)
    expect(error.code).toBe('network_error')
    expect(error.message).toMatch(/cannot reach the api/i)
  })

  it('flags 403 so the UI can show the permission page', () => {
    const error = toApiError({
      isAxiosError: true,
      message: 'Forbidden',
      response: {
        status: 403,
        data: {
          error: {
            code: 'permission_denied',
            detail: "Permission 'users:create' is required",
          },
        },
      },
    })
    expect(error.isPermissionDenied).toBe(true)
  })
})
