import type { FileMetadataFilters } from '@/schemas/fileMetadata'
import type { AuditLogFilters } from '@/schemas/log'

export const queryKeys = {
  me: ['me'] as const,

  users: {
    all: ['users'] as const,
    list: () => [...queryKeys.users.all, 'list'] as const,
    detail: (id: string) => [...queryKeys.users.all, 'detail', id] as const,
  },

  patients: {
    all: ['patients'] as const,
    list: () => [...queryKeys.patients.all, 'list'] as const,
    detail: (id: string) => [...queryKeys.patients.all, 'detail', id] as const,
  },

  roles: {
    all: ['roles'] as const,
    list: () => [...queryKeys.roles.all, 'list'] as const,
    detail: (id: string) => [...queryKeys.roles.all, 'detail', id] as const,
  },

  logs: {
    all: ['logs'] as const,
    list: (filters: AuditLogFilters = {}) =>
      [...queryKeys.logs.all, 'list', filters] as const,
    detail: (id: string) => [...queryKeys.logs.all, 'detail', id] as const,
  },

  applications: {
    all: ['applications'] as const,
    list: (patientId?: string) =>
      [...queryKeys.applications.all, 'list', patientId ?? null] as const,
    detail: (id: string) => [...queryKeys.applications.all, 'detail', id] as const,
  },

  applicationFiles: {
    all: ['application-files'] as const,
    list: (applicationId: string) =>
      [...queryKeys.applicationFiles.all, 'list', applicationId] as const,
    // Per file, fetched on demand when someone opens the metadata panel.
    metadata: (fileId: string) =>
      [...queryKeys.applicationFiles.all, 'metadata', fileId] as const,
    // One background batch, polled while it runs.
    uploadJob: (jobId: string) =>
      [...queryKeys.applicationFiles.all, 'upload-job', jobId] as const,
  },

  fileMetadata: {
    all: ['file-metadata'] as const,
    list: (filters: FileMetadataFilters = {}) =>
      [...queryKeys.fileMetadata.all, 'list', filters] as const,
  },

  deidentifiedFiles: {
    all: ['deidentified-files'] as const,
    list: (patientId?: string) =>
      [...queryKeys.deidentifiedFiles.all, 'list', patientId ?? null] as const,
  },
} as const
