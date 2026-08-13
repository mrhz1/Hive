import axios, { AxiosError } from 'axios'
import { getActiveUsername } from '@/lib/devIdentity'
import { apiErrorSchema } from '@/schemas/common'

/**
 * Where the API is, from the browser's point of view.
 *
 * With VITE_API_PROXY_TARGET set the dev server forwards `/api` to the
 * API (see vite.config.ts), so the page must ask its *own* origin --
 * that is the whole point, and calling the API directly anyway would put
 * the cross-origin request back and with it every CORS failure the
 * proxy exists to avoid. One variable decides both halves, because
 * setting the proxy and forgetting the base URL looks exactly like the
 * proxy not working.
 */
const baseURL = import.meta.env.VITE_API_PROXY_TARGET
  ? '/api'
  : (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8100')

/**
 * No default Content-Type, deliberately.
 *
 * Setting it here put `Content-Type: application/json` on *every*
 * request, including GETs that have no body to describe. That value is
 * not on the CORS safelist -- only form-urlencoded, multipart and
 * text/plain are -- so it turned every read into a preflighted request:
 * an OPTIONS before each one. A preflight carries no cookies by
 * definition, so anything authenticating in front of the API (Knox, the
 * Cloudera AI gateway) answers it instead of the API, and the browser
 * reports a CORS failure for a request the API never saw. Same-origin
 * it costs a wasted round trip and nothing else, which is why this only
 * ever showed up once deployed.
 *
 * Axios sets the header itself when there is a body to send, so posts
 * and puts are unaffected -- and those preflight regardless, a JSON
 * body being non-safelisted whatever we do here.
 */
export const api = axios.create({ baseURL })

api.interceptors.request.use((config) => {
  const username = getActiveUsername()
  if (username) {
    config.headers.set('REMOTE-USER', username)
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
