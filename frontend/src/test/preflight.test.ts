
import { describe, expect, it } from 'vitest'
import { api } from '@/lib/api/client'

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

const SAFELISTED = ['accept', 'accept-language', 'content-language']

describe('a read must not be preflighted', () => {
  it('sends no content-type on a GET -- there is no body to describe', async () => {
    expect(await headersOf(() => api.get('/patients'))).not.toContain('content-type')
  })

  it('sends nothing unsafelisted on a GET', async () => {
    const sent = await headersOf(() => api.get('/access-logs', { params: { limit: 500 } }))

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
