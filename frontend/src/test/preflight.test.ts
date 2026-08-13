/**
 * What the browser is asked to put on the wire.
 *
 * A cross-origin request is only sent straight out -- no preflight -- if
 * every header on it is CORS-safelisted. `Content-Type` counts as
 * safelisted only for form-urlencoded, multipart and text/plain; the
 * moment it says `application/json` the browser sends an OPTIONS first.
 *
 * That matters well beyond a wasted round trip. A preflight carries no
 * cookies by definition, so anything authenticating in front of the API
 * answers it rather than the API, and the browser reports a CORS failure
 * for a request the API never received. Adding one innocent default
 * header here is enough to break every read in a deployment while
 * everything still works locally, so it is pinned.
 */
import { describe, expect, it } from 'vitest'
import { api } from '@/lib/api/client'

/** The headers axios would actually send, without sending them. */
async function headersOf(call: () => Promise<unknown>): Promise<string[]> {
  let sent: string[] = []

  const previous = api.defaults.adapter
  api.defaults.adapter = async (config) => {
    sent = Object.keys(JSON.parse(JSON.stringify(config.headers))).map((name) =>
      name.toLowerCase()
    )
    return {
      data: {},
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    } as never
  }

  try {
    await call()
  } catch {
    // The stand-in body fails schema parsing; the headers are the point.
  } finally {
    api.defaults.adapter = previous
  }

  return sent
}

/** Everything a browser sends without asking permission first. */
const SAFELISTED = ['accept', 'accept-language', 'content-language']

describe('a read must not be preflighted', () => {
  it('sends no content-type on a GET -- there is no body to describe', async () => {
    expect(await headersOf(() => api.get('/patients'))).not.toContain('content-type')
  })

  it('sends nothing unsafelisted on a GET', async () => {
    const sent = await headersOf(() => api.get('/access-logs', { params: { limit: 500 } }))

    // REMOTE-USER is the exception, and only in a build given a dev
    // identity; a deployment leaves VITE_DEV_USERNAME unset and the
    // platform sets the header itself. See DEPLOYMENT.md.
    const unsafe = sent.filter(
      (name) => !SAFELISTED.includes(name) && name !== 'remote-user'
    )

    expect(unsafe).toEqual([])
  })

  it('still labels a body when there is one', async () => {
    expect(await headersOf(() => api.post('/patients', { a: 1 }))).toContain(
      'content-type'
    )
  })
})
