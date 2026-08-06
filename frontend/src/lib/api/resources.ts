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

/**
 * Parses a response against its schema so a backend shape change surfaces
 * here as a clear error rather than as `undefined` deep inside a
 * component. Every request funnels through this.
 */
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

/**
 * A cleared input submits '', but the column means "unknown" -- so the
 * empty strings become nulls here rather than being stored as empty
 * values the API would then have to distinguish from a real one.
 */
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

/**
 * The API stamps every actor column itself from the authenticated
 * caller, so the only things a client may send are the patient it is
 * for, where it is in the workflow, and the reviewer's note.
 */
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
      // webkitRelativePath preserves the folder structure in the name so
      // the original layout is recoverable; the API sanitises it before
      // anything touches the filesystem.
      form.append('files', file, file.webkitRelativePath || file.name)
    }
    if (description) form.append('description', description)

    return request(applicationFileListSchema, () =>
      // Let the browser set the multipart boundary; a manual
      // Content-Type would omit it and the server could not parse it.
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

  /**
   * Queues OCR + PII redaction. Returns immediately with the row marked
   * 'processing'; the result appears on a later read, not over a socket.
   */
  deidentify: (fileId: string) =>
    request(applicationFileSchema, () => api.post(`/files/${fileId}/deidentify`)),

  /**
   * Metadata extracted at upload time. Fetched on demand rather than
   * with the file list: it is a per-row detail nobody looks at until
   * they ask, and a DICOM header is larger than the row describing it.
   */
  metadata: (fileId: string) =>
    request(fileMetadataSchema, () => api.get(`/files/${fileId}/metadata`)),

  /**
   * Fetches the bytes as a Blob.
   *
   * Deliberately NOT a plain URL for the browser to navigate to: a
   * `window.open` on the endpoint bypasses axios, so the request carries
   * no identity and the API answers 401. Going through the client means
   * the same interceptor -- and whatever authentication Cloudera AI adds
   * later -- applies to file reads as to every other call.
   */
  fetchContent: async (fileId: string, deidentified = false): Promise<Blob> => {
    try {
      const response = await api.get(`/files/${fileId}/content`, {
        responseType: 'blob',
        params: deidentified ? { deidentified: true } : undefined,
      })
      return response.data as Blob
    } catch (error) {
      // With responseType 'blob' an error body arrives as a Blob too, so
      // the JSON envelope has to be read back out before it can be
      // parsed -- otherwise every failure reads "unexpected error".
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

export type { ApplicationFile, AuditLog, Patient, Role, User }
