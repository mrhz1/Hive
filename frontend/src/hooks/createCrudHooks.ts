import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError } from '@/lib/api/client'

export type ResourceApi<TEntity, TForm> = {
  list: () => Promise<TEntity[]>
  get: (id: string) => Promise<TEntity>
  create: (values: TForm) => Promise<TEntity>
  update: (id: string, values: TForm) => Promise<TEntity>
  remove: (id: string) => Promise<void>
}

export type ResourceKeys = {
  all: readonly unknown[]
  list: () => readonly unknown[]
  detail: (id: string) => readonly unknown[]
}

export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return fallback
}

export function createCrudHooks<TEntity, TForm>(config: {
  api: ResourceApi<TEntity, TForm>
  keys: ResourceKeys
  /** Singular, capitalised, e.g. 'User' -- used in toast copy. */
  label: string
  /** Extra key prefixes to invalidate, e.g. audit logs after a write. */
  alsoInvalidate?: readonly (readonly unknown[])[]
}) {
  const { api, keys, label, alsoInvalidate = [] } = config

  function useInvalidate() {
    const queryClient = useQueryClient()
    return () => {
      void queryClient.invalidateQueries({ queryKey: keys.all })
      for (const key of alsoInvalidate) {
        void queryClient.invalidateQueries({ queryKey: key })
      }
    }
  }

  function useList(options?: { enabled?: boolean }) {
    return useQuery({
      queryKey: keys.list(),
      queryFn: api.list,
      enabled: options?.enabled ?? true,
    })
  }

  function useDetail(id: string | undefined, options?: { enabled?: boolean }) {
    return useQuery({
      queryKey: keys.detail(id ?? ''),
      queryFn: () => api.get(id as string),
      enabled: Boolean(id) && (options?.enabled ?? true),
    })
  }

  function useCreate() {
    const invalidate = useInvalidate()
    return useMutation({
      mutationFn: (values: TForm) => api.create(values),
      onSuccess: () => {
        invalidate()
        toast.success(`${label} created`)
      },
      onError: (error) => {
        toast.error(errorMessage(error, `Could not create ${label.toLowerCase()}`))
      },
    })
  }

  function useUpdate() {
    const invalidate = useInvalidate()
    return useMutation({
      mutationFn: ({ id, values }: { id: string; values: TForm }) =>
        api.update(id, values),
      onSuccess: () => {
        invalidate()
        toast.success(`${label} updated`)
      },
      onError: (error) => {
        toast.error(errorMessage(error, `Could not update ${label.toLowerCase()}`))
      },
    })
  }

  function useRemove() {
    const invalidate = useInvalidate()
    return useMutation({
      mutationFn: (id: string) => api.remove(id),
      onSuccess: () => {
        invalidate()
        toast.success(`${label} deleted`)
      },
      onError: (error) => {
        toast.error(errorMessage(error, `Could not delete ${label.toLowerCase()}`))
      },
    })
  }

  return { useList, useDetail, useCreate, useUpdate, useRemove }
}
