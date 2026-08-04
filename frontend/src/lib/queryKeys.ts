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

  customers: {
    all: ['customers'] as const,
    list: () => [...queryKeys.customers.all, 'list'] as const,
    detail: (id: string) => [...queryKeys.customers.all, 'detail', id] as const,
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

  customerFiles: {
    all: ['customer-files'] as const,
    // Scoped by customer: uploading for one customer must not invalidate
    // another's list.
    list: (customerId: string) =>
      [...queryKeys.customerFiles.all, 'list', customerId] as const,
  },
} as const
