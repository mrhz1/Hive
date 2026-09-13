import axios, { AxiosError } from 'axios'
import { getActiveUsername } from '@/lib/devIdentity'
import { apiErrorSchema } from '@/schemas/common'

const baseURL = import.meta.env.VITE_API_PROXY_TARGET
  ? '/api'
  : (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8100')

export const api = axios.create({ baseURL })

api.interceptors.request.use((config) => {
  const username = getActiveUsername()
  if (username) {
    config.headers.set('REMOTE-USER', username)
  }
  return config
})

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fieldErrors: Array<{ field: string; message: string }>

  constructor(
    status: number,
    code: string,
    message: string,
    fieldErrors: Array<{ field: string; message: string }> = []
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.fieldErrors = fieldErrors
  }

  get isPermissionDenied() {
    return this.status === 403
  }

  get isUnauthenticated() {
    return this.status === 401
  }

  get isNotFound() {
    return this.status === 404
  }

  get isConflict() {
    return this.status === 409
  }
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error

  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError

    if (!axiosError.response) {
      return new ApiError(
        0,
        'network_error',
        'Cannot reach the API. Check that it is running and reachable.'
      )
    }

    const status = axiosError.response.status
    const parsed = apiErrorSchema.safeParse(axiosError.response.data)

    if (parsed.success) {
      const { code, detail, fields } = parsed.data.error
      const fieldErrors = (fields ?? []).map((f) => ({

        field: String(f.loc[f.loc.length - 1] ?? ''),
        message: f.msg,
      }))
      return new ApiError(status, code, detail, fieldErrors)
    }

    return new ApiError(status, 'unexpected_error', axiosError.message)
  }

  if (error instanceof Error) {
    return new ApiError(0, 'unexpected_error', error.message)
  }

  return new ApiError(0, 'unexpected_error', 'An unexpected error occurred')
}
