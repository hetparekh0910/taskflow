// Tiny fetch wrapper: base URL, JWT header, automatic refresh-on-401, typed errors.
const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''

const ACCESS = 'tf_access'
const REFRESH = 'tf_refresh'

export const tokens = {
  get access() { return localStorage.getItem(ACCESS) },
  get refresh() { return localStorage.getItem(REFRESH) },
  set(a: string, r?: string) {
    localStorage.setItem(ACCESS, a)
    if (r) localStorage.setItem(REFRESH, r)
  },
  clear() { localStorage.removeItem(ACCESS); localStorage.removeItem(REFRESH) },
}

export class ApiError extends Error {
  status: number
  data: any
  constructor(status: number, data: any) {
    super(extractMessage(data) || `Request failed (${status})`)
    this.status = status
    this.data = data
  }
  get isPlanLimit() { return this.status === 402 && this.data?.code === 'plan_limit' }
}

export function extractMessage(data: any): string {
  if (!data) return ''
  if (typeof data === 'string') return data
  if (data.detail) return String(data.detail)
  const parts: string[] = []
  for (const [k, v] of Object.entries(data)) {
    if (k === 'code') continue
    const msg = Array.isArray(v) ? v.join(' ') : typeof v === 'object' ? JSON.stringify(v) : String(v)
    parts.push(k === 'non_field_errors' ? msg : `${k}: ${msg}`)
  }
  return parts.join(' · ')
}

let refreshing: Promise<boolean> | null = null
async function refreshAccess(): Promise<boolean> {
  if (!tokens.refresh) return false
  refreshing ??= fetch(`${BASE}/api/auth/refresh/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh: tokens.refresh }),
  })
    .then(async (r) => {
      if (!r.ok) return false
      tokens.set((await r.json()).access)
      return true
    })
    .catch(() => false)
    .finally(() => { refreshing = null })
  return refreshing
}

type Opts = { method?: string; body?: unknown; form?: FormData; auth?: boolean; params?: Record<string, string | number | boolean | undefined | null> }

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  const { method = 'GET', body, form, auth = true, params } = opts
  let url = `${BASE}/api${path}`
  if (params) {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
    const s = q.toString()
    if (s) url += (url.includes('?') ? '&' : '?') + s
  }
  const doFetch = () => {
    const headers: Record<string, string> = {}
    if (auth && tokens.access) headers.Authorization = `Bearer ${tokens.access}`
    if (!form && body !== undefined) headers['Content-Type'] = 'application/json'
    return fetch(url, { method, headers, body: form ?? (body !== undefined ? JSON.stringify(body) : undefined) })
  }
  let res = await doFetch()
  if (res.status === 401 && auth && (await refreshAccess())) res = await doFetch()
  if (res.status === 401 && auth) {
    tokens.clear()
    window.dispatchEvent(new Event('tf:logout'))
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  let data: any = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) {
    if (res.status === 402 && data?.code === 'plan_limit') window.dispatchEvent(new CustomEvent('tf:planlimit', { detail: data }))
    throw new ApiError(res.status, data)
  }
  return data as T
}

/** Download a membership-checked file (needs the auth header, so not a plain <a href>). */
export async function downloadFile(path: string, filename: string) {
  const res = await fetch(`${BASE}${path}`, { headers: { Authorization: `Bearer ${tokens.access}` } })
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null))
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}
