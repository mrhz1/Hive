import axios, { AxiosError } from 'axios'
import { getActiveUserId } from '@/lib/devIdentity'
import { apiErrorSchema } from '@/schemas/common'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8100',
  headers: { 'Content-Type': 'application/json' },
})

/**
 * Caller identity.
 *
 * There is no login: on Cloudera AI the platform authenticates the user
 * and the API resolves them, so the app just asks /me who it is. Locally
 * an id comes from VITE_DEV_USER_ID (optionally overridden by the user
 * switcher) and is sent as X-User-Id -- the same header app/security.py
 * reads.
 *
 * This is configuration, not an environment branch: when no id is
 * configured the header is simply omitted and the API decides.
 *
 * Resolved per request rather than once at module load, so switching
 * identity does not require a fresh module graph.
 */
api.interceptors.request.use((config) => {
  const userId = getActiveUserId()
  if (userId) {
    config.headers.set('X-User-Id', userId)
  }
  return config
})

/** Normalised error every layer above the client can rely on. */
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

  /** 409 from a uniqueness pre-check (username/email/phone/role name). */
  get isConflict() {
    return this.status === 409
  }
}

/**
 * Turns anything axios throws into an ApiError with a message worth
 * showing a user. The API's own envelope is
 * `{error: {code, detail, fields?}}`; network failures never reach it.
 */
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
        // FastAPI reports loc as ['body', 'email']; the field name is last.
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
