import { describe, expect, it } from 'vitest'
import { ApiError, toApiError } from '@/lib/api/client'
import { ALL_PERMISSIONS } from '@/schemas/common'
import { userFormSchema } from '@/schemas/user'
import { EMPTY_PATIENT_FORM, patientFormSchema } from '@/schemas/patient'
import { roleFormSchema } from '@/schemas/role'

describe('permissions', () => {
  it('enumerates exactly the 24 grants the API recognises', () => {
    // Five CRUD models × four actions, plus the four files:* grants.
    expect(ALL_PERMISSIONS).toHaveLength(24)
    expect(ALL_PERMISSIONS).toContain('user:view')
    expect(ALL_PERMISSIONS).toContain('log:delete')
  })

  it('gives files its own actions', () => {
    for (const action of ['read', 'upload', 'download', 'delete']) {
      expect(ALL_PERMISSIONS).toContain(`files:${action}`)
    }
  })

  it('does not leak the files actions onto the CRUD models', () => {
    // A cross-product would put 'user:download' in the role editor.
    expect(ALL_PERMISSIONS).not.toContain('user:download')
    expect(ALL_PERMISSIONS).not.toContain('role:upload')
    expect(ALL_PERMISSIONS).not.toContain('files:view')
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

describe('patientFormSchema', () => {
  const valid = {
    ...EMPTY_PATIENT_FORM,
    fstname: 'Jane',
    lstname: 'Doe',
    ptemail: 'jane@example.com',
    ptphone: '+1 555 010 0100',
    original_file_path: '/data/jane.pdf',
  }

  it('accepts international phone formats', () => {
    expect(patientFormSchema.safeParse(valid).success).toBe(true)
    expect(
      patientFormSchema.safeParse({ ...valid, ptphone: '(415) 555-0182' }).success
    ).toBe(true)
  })

  it('rejects a phone number containing letters', () => {
    expect(patientFormSchema.safeParse({ ...valid, ptphone: 'call-me' }).success).toBe(
      false
    )
  })

  it('requires an original file path', () => {
    expect(
      patientFormSchema.safeParse({ ...valid, original_file_path: '' }).success
    ).toBe(false)
  })

  it('accepts a record carrying only one of the three identifiers', () => {
    const base = { ...EMPTY_PATIENT_FORM, original_file_path: '/data/x.pdf' }

    expect(patientFormSchema.safeParse({ ...base, fstname: 'Jane' }).success).toBe(true)
    expect(patientFormSchema.safeParse({ ...base, lstname: 'Doe' }).success).toBe(true)
    expect(
      patientFormSchema.safeParse({ ...base, ptemail: 'jane@example.com' }).success
    ).toBe(true)
  })

  it('drops a name as long as another identifier remains', () => {
    expect(patientFormSchema.safeParse({ ...valid, fstname: '' }).success).toBe(true)
    expect(patientFormSchema.safeParse({ ...valid, lstname: '' }).success).toBe(true)
  })

  it('rejects a record identified by nothing, under the first name field', () => {
    const result = patientFormSchema.safeParse({
      ...valid,
      fstname: '   ',
      lstname: '',
      ptemail: '',
    })

    expect(result.success).toBe(false)
    // Reported against an input, not floating above the form.
    expect(result.error?.issues.map((i) => i.path.join('.'))).toContain('fstname')
  })

  it('rejects a date that is not YYYY-MM-DD', () => {
    expect(patientFormSchema.safeParse({ ...valid, dt_b: '01/02/1990' }).success).toBe(
      false
    )
    expect(patientFormSchema.safeParse({ ...valid, dt_b: '1990-01-02' }).success).toBe(
      true
    )
  })

  it('rejects a malformed email but allows an empty one', () => {
    expect(patientFormSchema.safeParse({ ...valid, ptemail: 'nope' }).success).toBe(false)
    expect(patientFormSchema.safeParse({ ...valid, ptemail: '' }).success).toBe(true)
  })
})

describe('roleFormSchema', () => {
  it('accepts known permissions', () => {
    const result = roleFormSchema.safeParse({
      name: 'support',
      permissions: ['user:view', 'patient:update'],
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
            detail: "Permission 'user:create' is required",
          },
        },
      },
    })
    expect(error.isPermissionDenied).toBe(true)
  })
})
