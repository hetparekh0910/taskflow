import { describe, expect, it, vi } from 'vitest'
import { ApiError, api, extractMessage, tokens } from './client'

const json = (status: number, body: unknown) => new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('extractMessage', () => {
  it('prefers `detail`', () => expect(extractMessage({ detail: 'Nope' })).toBe('Nope'))
  it('joins field errors', () => expect(extractMessage({ email: ['Taken.'], password: ['Too short.'] })).toBe('email: Taken. · password: Too short.'))
  it('hides non_field_errors keys and ignores `code`', () => expect(extractMessage({ non_field_errors: ['Bad.'], code: 'x' })).toBe('Bad.'))
  it('handles strings and empty values', () => { expect(extractMessage('plain')).toBe('plain'); expect(extractMessage(null)).toBe('') })
})

describe('api()', () => {
  it('sends the bearer token and JSON body, and builds query strings (skipping empty params)', async () => {
    tokens.set('abc')
    const f = vi.fn().mockResolvedValue(json(200, { ok: true }))
    vi.stubGlobal('fetch', f)
    await api('/w/acme/issues/', { method: 'POST', body: { title: 'x' }, params: { q: 'bug', empty: '', none: undefined, n: 2 } })
    const [url, init] = f.mock.calls[0]
    expect(url).toBe('/api/w/acme/issues/?q=bug&n=2')
    expect(init.headers.Authorization).toBe('Bearer abc')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(init.body).toBe('{"title":"x"}')
  })
  it('does not send auth for public calls and returns undefined on 204', async () => {
    tokens.set('abc')
    const f = vi.fn().mockResolvedValue(json(204, null))
    vi.stubGlobal('fetch', f)
    expect(await api('/auth/login/', { method: 'POST', body: {}, auth: false })).toBeUndefined()
    expect(f.mock.calls[0][1].headers.Authorization).toBeUndefined()
  })
  it('throws ApiError with a readable message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(400, { title: ['Required.'] })))
    await expect(api('/x/')).rejects.toMatchObject({ status: 400, message: 'title: Required.' })
  })
  it('refreshes an expired access token once and retries the request', async () => {
    tokens.set('old', 'refresh1')
    const f = vi.fn()
      .mockResolvedValueOnce(json(401, { detail: 'expired' }))
      .mockResolvedValueOnce(json(200, { access: 'new' }))
      .mockResolvedValueOnce(json(200, { hello: 'world' }))
    vi.stubGlobal('fetch', f)
    expect(await api('/auth/me/')).toEqual({ hello: 'world' })
    expect(f).toHaveBeenCalledTimes(3)
    expect(f.mock.calls[1][0]).toBe('/api/auth/refresh/')
    expect(f.mock.calls[2][1].headers.Authorization).toBe('Bearer new')
    expect(tokens.access).toBe('new')
  })
  it('logs out (clears tokens, fires event) when refresh also fails', async () => {
    tokens.set('old', 'bad')
    const onLogout = vi.fn(); window.addEventListener('tf:logout', onLogout)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(401, { detail: 'no' })))
    await expect(api('/auth/me/')).rejects.toBeInstanceOf(ApiError)
    expect(tokens.access).toBeNull()
    expect(onLogout).toHaveBeenCalled()
    window.removeEventListener('tf:logout', onLogout)
  })
  it('broadcasts plan-limit 402s so the UI can show the upgrade prompt', async () => {
    const payload = { detail: 'Your Free plan allows 3 members.', code: 'plan_limit', resource: 'members', limit: 3 }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(402, payload)))
    const seen = vi.fn(); window.addEventListener('tf:planlimit', seen as EventListener)
    const err = await api('/w/a/invitations/', { method: 'POST', body: {} }).catch((e) => e)
    expect(err.isPlanLimit).toBe(true)
    expect((seen.mock.calls[0][0] as CustomEvent).detail.resource).toBe('members')
    window.removeEventListener('tf:planlimit', seen as EventListener)
  })
})
