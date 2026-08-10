import axios from 'axios'
import { apiErrorSchema } from '@/schemas/common'
import type { z } from 'zod'
import { ApiError, api, toApiError } from './client'
import {
  auditLogListSchema,
  auditLogSchema,
  type AuditLog,
  type AuditLogFilters,
} from '@/schemas/log'
import {
  PATIENT_FIELD_NAMES,
  patientListSchema,
  patientSchema,
  type Patient,
  type PatientFormValues,
} from '@/schemas/patient'
import {
  patientApplicationListSchema,
  patientApplicationSchema,
} from '@/schemas/patientApplication'
import {
  deidentifiedFileListSchema,
  deidentifiedFileSchema,
} from '@/schemas/deidentifiedFile'
import {
  applicationFileListSchema,
  applicationFileSchema,
  fileMetadataSchema,
  type ApplicationFile,
} from '@/schemas/applicationFile'
import {
  roleListSchema,
  roleSchema,
  type Role,
  type RoleFormValues,
} from '@/schemas/role'
import {
  userListSchema,
  userSchema,
  type ProfileFormValues,
  type User,
  type UserFormValues,
} from '@/schemas/user'

async function request<T>(
  schema: z.ZodType<T>,
  fn: () => Promise<{ data: unknown }>
): Promise<T> {
  try {
    const response = await fn()
    const parsed = schema.safeParse(response.data)
    if (!parsed.success) {
      throw Object.assign(new Error('The API returned data in an unexpected shape'), {
        name: 'SchemaError',
        cause: parsed.error,
      })
    }
    return parsed.data
  } catch (error) {
    if (error instanceof Error && error.name === 'SchemaError') throw error
    throw toApiError(error)
  }
}

/** '' from a <select> means "no role"; the API wants null. */
function toUserPayload(values: UserFormValues) {
  return { ...values, role_id: values.role_id === '' ? null : values.role_id }
}

export const usersApi = {
  list: () => request(userListSchema, () => api.get('/users')),
  get: (id: string) => request(userSchema, () => api.get(`/users/${id}`)),
  create: (values: UserFormValues) =>
    request(userSchema, () => api.post('/users', toUserPayload(values))),
  update: (id: string, values: UserFormValues) =>
    request(userSchema, () => api.put(`/users/${id}`, toUserPayload(values))),
  remove: async (id: string) => {
    try {
      await api.delete(`/users/${id}`)
    } catch (error) {
      throw toApiError(error)
    }
  },
}

function toPatientPayload(values: PatientFormValues) {
  const payload: Record<string, unknown> = {}
  for (const name of PATIENT_FIELD_NAMES) {
    const value = values[name]
    payload[name] = typeof value === 'string' && value.trim() === '' ? null : value
  }
  return payload
}

export const patientsApi = {
  list: () => request(patientListSchema, () => api.get('/patients')),
  get: (id: string) => request(patientSchema, () => api.get(`/patients/${id}`)),
  create: (values: PatientFormValues) =>
    request(patientSchema, () => api.post('/patients', toPatientPayload(values))),
  update: (id: string, values: PatientFormValues) =>
    request(patientSchema, () => api.put(`/patients/${id}`, toPatientPayload(values))),
  remove: async (id: string) => {
    try {
      await api.delete(`/patients/${id}`)
    } catch (error) {
      throw toApiError(error)
    }
  },
}

export type ApplicationPayload = {
  patient_id?: string
  status?: string
  description?: string | null
}

export const applicationsApi = {
  list: (patientId?: string) =>
    request(patientApplicationListSchema, () =>
      api.get('/applications', { params: patientId ? { patient_id: patientId } : undefined })
    ),
  get: (id: string) =>
    request(patientApplicationSchema, () => api.get(`/applications/${id}`)),
  create: (values: ApplicationPayload) =>
    request(patientApplicationSchema, () => api.post('/applications', values)),
  update: (id: string, values: ApplicationPayload) =>
    request(patientApplicationSchema, () => api.put(`/applications/${id}`, values)),
  remove: async (id: string) => {
    try {
      await api.delete(`/applications/${id}`)
    } catch (error) {
      throw toApiError(error)
    }
  },
}

export const rolesApi = {
  list: () => request(roleListSchema, () => api.get('/roles')),
  get: (id: string) => request(roleSchema, () => api.get(`/roles/${id}`)),
  create: (values: RoleFormValues) =>
    request(roleSchema, () => api.post('/roles', values)),
  update: (id: string, values: RoleFormValues) =>
    request(roleSchema, () => api.put(`/roles/${id}`, values)),
  remove: async (id: string) => {
    try {
      await api.delete(`/roles/${id}`)
    } catch (error) {
      throw toApiError(error)
    }
  },
}

export const logsApi = {
  list: (filters: AuditLogFilters = {}) =>
    request(auditLogListSchema, () => api.get('/logs', { params: filters })),
  get: (id: string) => request(auditLogSchema, () => api.get(`/logs/${id}`)),
}

export const applicationFilesApi = {
  list: (applicationId: string) =>
    request(applicationFileListSchema, () =>
      api.get(`/applications/${applicationId}/files`)
    ),

  /** Uploads a whole folder's worth of files in one multipart request. */
  upload: (applicationId: string, files: File[], description?: string) => {
    const form = new FormData()
    for (const file of files) {
      form.append('files', file, file.webkitRelativePath || file.name)
    }
    if (description) form.append('description', description)

    return request(applicationFileListSchema, () =>
      api.post(`/applications/${applicationId}/files`, form, {
        headers: { 'Content-Type': undefined },
      })
    )
  },

  remove: async (fileId: string) => {
    try {
      await api.delete(`/files/${fileId}`)
    } catch (error) {
      throw toApiError(error)
    }
  },

  deidentify: (fileId: string) =>
    request(applicationFileSchema, () => api.post(`/files/${fileId}/deidentify`)),

  metadata: (fileId: string) =>
    request(fileMetadataSchema, () => api.get(`/files/${fileId}/metadata`)),

  fetchContent: async (fileId: string, deidentified = false): Promise<Blob> => {
    try {
      const response = await api.get(`/files/${fileId}/content`, {
        responseType: 'blob',
        params: deidentified ? { deidentified: true } : undefined,
      })
      return response.data as Blob
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.data instanceof Blob) {
        const text = await error.response.data.text()
        try {
          const parsed = apiErrorSchema.parse(JSON.parse(text))
          throw new ApiError(
            error.response.status,
            parsed.error.code,
            parsed.error.detail
          )
        } catch (parseError) {
          // Not the API envelope: fall through to the generic mapping.
          if (parseError instanceof ApiError) throw parseError
        }
      }
      throw toApiError(error)
    }
  },
}

export const meApi = {
  get: () => request(userSchema, () => api.get('/me')),
  update: (values: ProfileFormValues) =>
    request(userSchema, () => api.put('/me', values)),
}

export const deidentifiedFilesApi = {
  list: (patientId?: string) =>
    request(deidentifiedFileListSchema, () =>
      api.get('/files-library', {
        params: patientId ? { patient_id: patientId } : undefined,
      })
    ),

  upload: (patientId: string, file: File, replacesFileId?: string) => {
    const form = new FormData()
    form.append('patient_id', patientId)
    form.append('file', file, file.name)
    if (replacesFileId) form.append('replaces_file_id', replacesFileId)

    return request(deidentifiedFileSchema, () =>
      api.post('/files-library', form, {
        headers: { 'Content-Type': undefined },
      })
    )
  },

  remove: async (fileId: string) => {
    try {
      await api.delete(`/files-library/${fileId}`)
    } catch (error) {
      throw toApiError(error)
    }
  },

  fetchContent: async (fileId: string): Promise<Blob> => {
    try {
      const response = await api.get(`/files-library/${fileId}/content`, {
        responseType: 'blob',
      })
      return response.data as Blob
    } catch (error) {
      throw toApiError(error)
    }
  },
}

export type { ApplicationFile, AuditLog, Patient, Role, User }
