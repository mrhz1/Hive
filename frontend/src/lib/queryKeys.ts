import type { AuditLogFilters } from '@/schemas/log'

/**
 * Hierarchical query keys. Because every users key starts with ['users'],
 * invalidating ['users'] after a mutation refetches the list and every
 * individual user detail in one call -- no key bookkeeping at call sites.
 */
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

  patientFiles: {
    all: ['patient-files'] as const,
    // Scoped by patient: uploading for one patient must not invalidate
    // another's list.
    list: (patientId: string) =>
      [...queryKeys.patientFiles.all, 'list', patientId] as const,
  },
} as const
