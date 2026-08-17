import axios from 'axios'
import { apiErrorSchema } from '@/schemas/common'
import type { z } from 'zod'
import { ApiError, api, toApiError } from './client'
import {
  accessLogListSchema,
  type AccessLogFilters,
} from '@/schemas/accessLog'
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
  bulkResultSchema,
  deidProgressListSchema,
  fileMetadataSchema,
  uploadJobSchema,
  wordPreviewSchema,
  type ApplicationFile,
  type ImagePreview,
} from '@/schemas/applicationFile'
import {
  activeFilters,
  fileMetadataRowListSchema,
  type FileMetadataFilters,
} from '@/schemas/fileMetadata'
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

/**
 * A rendered preview plus the frame count the API reports alongside it.
 *
 * The caller owns the object URL and must revoke it -- these are images,
 * and a modal that opens a hundred frames without revoking leaks them
 * all until the tab closes.
 */
async function fetchImagePreview(
  path: string,
  frame: number,
  deidentified: boolean
): Promise<ImagePreview> {
  try {
    const response = await api.get(path, {
      responseType: 'blob',
      params: {
        ...(frame ? { frame } : {}),
        ...(deidentified ? { deidentified: true } : {}),
      },
    })
    const frames = Number(response.headers['x-frame-count'] ?? 1)
    return {
      url: URL.createObjectURL(response.data as Blob),
      frames: Number.isFinite(frames) && frames > 0 ? frames : 1,
    }
  } catch (error) {
    throw await blobError(error)
  }
}

/**
 * Errors from a responseType:'blob' request arrive as a Blob too, so the
 * API's message is in there rather than on the parsed body.
 */
async function blobError(error: unknown): Promise<unknown> {
  if (axios.isAxiosError(error) && error.response?.data instanceof Blob) {
    try {
      const parsed = apiErrorSchema.parse(
        JSON.parse(await error.response.data.text())
      )
      return new ApiError(
        error.response.status,
        parsed.error.code,
        parsed.error.detail
      )
    } catch {
      // Not the API envelope; fall through to the generic mapping.
    }
  }
  return toApiError(error)
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
  /** '' from the assignee <select> means "nobody"; the API wants null. */
  assigned_to_id?: string | null
  original_file_path?: string | null
}

/** Blank means "not set", which the API spells as null. */
function toApplicationPayload(values: ApplicationPayload) {
  const payload: ApplicationPayload = { ...values }
  if ('assigned_to_id' in values) {
    payload.assigned_to_id = values.assigned_to_id || null
  }
  if ('original_file_path' in values) {
    payload.original_file_path = values.original_file_path?.trim() || null
  }
  return payload
}

export const applicationsApi = {
  list: (patientId?: string) =>
    request(patientApplicationListSchema, () =>
      api.get('/applications', { params: patientId ? { patient_id: patientId } : undefined })
    ),
  get: (id: string) =>
    request(patientApplicationSchema, () => api.get(`/applications/${id}`)),
  create: (values: ApplicationPayload) =>
    request(patientApplicationSchema, () =>
      api.post('/applications', toApplicationPayload(values))
    ),
  update: (id: string, values: ApplicationPayload) =>
    request(patientApplicationSchema, () =>
      api.put(`/applications/${id}`, toApplicationPayload(values))
    ),

  reject: (id: string, reason: string) =>
    request(patientApplicationSchema, () =>
      api.post(`/applications/${id}/reject`, { reason })
    ),

  remove: async (id: string, reason: string) => {
    try {
      await api.delete(`/applications/${id}`, { params: { reason } })
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

export const accessLogsApi = {
  list: (filters: AccessLogFilters = {}) =>
    request(accessLogListSchema, () =>
      api.get('/access-logs', { params: filters })
    ),
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

  /**
   * The same batch, handed off rather than waited on: the response comes
   * back once the bytes are staged, and the job says how the moving and
   * recording went afterwards.
   */
  uploadInBackground: (
    applicationId: string,
    files: File[],
    description?: string
  ) => {
    const form = new FormData()
    for (const file of files) {
      form.append('files', file, file.webkitRelativePath || file.name)
    }
    if (description) form.append('description', description)

    return request(uploadJobSchema, () =>
      api.post(`/applications/${applicationId}/files/background`, form, {
        headers: { 'Content-Type': undefined },
      })
    )
  },

  uploadJob: (jobId: string) =>
    request(uploadJobSchema, () => api.get(`/upload-jobs/${jobId}`)),

  /** One DICOM frame as a PNG, plus how many frames there are. */
  previewImage: (fileId: string, frame = 0, deidentified = false) =>
    fetchImagePreview(`/files/${fileId}/image`, frame, deidentified),

  /** A Word document as text -- see app/preview.py for why not HTML. */
  previewText: (fileId: string, deidentified = false) =>
    request(wordPreviewSchema, () =>
      api.get(`/files/${fileId}/text`, {
        params: deidentified ? { deidentified: true } : undefined,
      })
    ),

  remove: async (fileId: string) => {
    try {
      await api.delete(`/files/${fileId}`)
    } catch (error) {
      throw toApiError(error)
    }
  },

  deidentify: (fileId: string) =>
    request(applicationFileSchema, () => api.post(`/files/${fileId}/deidentify`)),

  /**
   * Live progress for every running de-identification on the application.
   *
   * Read off a file the Job writes to shared storage, not the database --
   * a Hive write per page would cost seconds against a page that takes
   * twenty. Files that are not running are simply absent.
   */
  deidProgress: (applicationId: string) =>
    request(deidProgressListSchema, () =>
      api.get(`/applications/${applicationId}/files/deid-progress`)
    ),

  /**
   * One request for the whole application. An application can hold
   * thousands of documents, and the browser firing that many is both
   * slow and a good way to have half of them rejected.
   */
  deidentifyAll: (applicationId: string) =>
    request(bulkResultSchema, () =>
      api.post(`/applications/${applicationId}/files/deidentify-all`)
    ),

  approveAll: (applicationId: string) =>
    request(bulkResultSchema, () =>
      api.post(`/applications/${applicationId}/files/approve-all`)
    ),

  review: (fileId: string, reviewStatus: 'approved' | 'rejected', note?: string) =>
    request(applicationFileSchema, () =>
      api.post(`/files/${fileId}/review`, {
        review_status: reviewStatus,
        review_note: note ?? null,
      })
    ),

  /** The original's stored metadata, or the redacted copy's, read live. */
  metadata: (fileId: string, deidentified = false) =>
    request(fileMetadataSchema, () =>
      api.get(`/files/${fileId}/metadata`, {
        params: deidentified ? { deidentified: true } : undefined,
      })
    ),

  exportMetadata: async (
    fileId: string,
    fields?: string[],
    deidentified = false
  ): Promise<Blob> => {
    try {
      const response = await api.get(`/files/${fileId}/metadata/export`, {
        responseType: 'blob',
        params: {
          ...(fields?.length ? { fields: fields.join(',') } : {}),
          ...(deidentified ? { deidentified: true } : {}),
        },
      })
      return response.data as Blob
    } catch (error) {
      throw toApiError(error)
    }
  },

  /**
   * A document that is already redacted, attached as it stands. There is
   * no original behind it and nothing to run over it, so it arrives
   * done -- see the endpoint in app/routers/patient_application_files.py.
   */
  uploadDeidentified: (
    applicationId: string,
    file: File,
    description?: string
  ) => {
    const form = new FormData()
    form.append('file', file, file.name)
    if (description) form.append('description', description)

    return request(applicationFileSchema, () =>
      api.post(`/applications/${applicationId}/files/deidentified`, form, {
        headers: { 'Content-Type': undefined },
      })
    )
  },

  /**
   * The bytes. `download` is what separates the two events in the access
   * log -- opening a document in the viewer is a read, and only the
   * Download button takes a copy away, which needs `files:download`.
   */
  fetchContent: async (
    fileId: string,
    deidentified = false,
    download = false
  ): Promise<Blob> => {
    try {
      const response = await api.get(`/files/${fileId}/content`, {
        responseType: 'blob',
        params: {
          ...(deidentified ? { deidentified: true } : {}),
          ...(download ? { download: true } : {}),
        },
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

export const fileMetadataApi = {
  list: (filters: FileMetadataFilters = {}) =>
    request(fileMetadataRowListSchema, () =>
      api.get('/file-metadata', { params: activeFilters(filters) })
    ),

  /** The filtered table as a workbook -- same filters, same rows. */
  export: async (filters: FileMetadataFilters = {}): Promise<Blob> => {
    try {
      const response = await api.get('/file-metadata/export', {
        responseType: 'blob',
        params: activeFilters(filters),
      })
      return response.data as Blob
    } catch (error) {
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

  fetchContent: async (fileId: string, download = false): Promise<Blob> => {
    try {
      const response = await api.get(`/files-library/${fileId}/content`, {
        responseType: 'blob',
        params: download ? { download: true } : undefined,
      })
      return response.data as Blob
    } catch (error) {
      throw toApiError(error)
    }
  },

  previewImage: (fileId: string, frame = 0) =>
    fetchImagePreview(`/files-library/${fileId}/image`, frame, false),

  previewText: (fileId: string) =>
    request(wordPreviewSchema, () => api.get(`/files-library/${fileId}/text`)),
}

export type { ApplicationFile, AuditLog, Patient, Role, User }
