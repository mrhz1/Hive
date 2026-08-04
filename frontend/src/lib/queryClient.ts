import { QueryClient } from '@tanstack/react-query'
import { ApiError } from './api/client'

/**
 * Cache policy is tuned for a Hive-backed API, where a list query costs
 * seconds rather than milliseconds:
 *
 *  - staleTime 60s: reads are served from cache for a minute instead of
 *    refetching on every mount/navigation. Mutations explicitly
 *    invalidate, so a create/update/delete still shows fresh data
 *    immediately -- the cache never goes stale in a way the user sees.
 *  - gcTime 5min: navigating away and back is instant.
 *  - no refetchOnWindowFocus: on this backend it would fire an expensive
 *    query every time the user alt-tabs, for no benefit.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // Retrying a 4xx just repeats the same rejection; only transient
        // failures (network, 5xx) are worth another attempt.
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
          return false
        }
        return failureCount < 2
      },
    },
    mutations: {
      retry: false,
    },
  },
})
