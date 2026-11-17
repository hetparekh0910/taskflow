import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, tokens } from '../api/client'
import type { User } from '../api/types'

interface AuthCtx {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (data: { email: string; password: string; full_name?: string; workspace_name?: string; invite_token?: string }) => Promise<string | null>
  logout: () => void
}
const Ctx = createContext<AuthCtx>(null as never)
export const useAuth = () => useContext(Ctx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(!!tokens.access)

  useEffect(() => {
    if (!tokens.access) return
    api<User>('/auth/me/').then(setUser).catch(() => tokens.clear()).finally(() => setLoading(false))
  }, [])

  const logout = useCallback(() => { tokens.clear(); setUser(null) }, [])
  useEffect(() => {
    window.addEventListener('tf:logout', logout)
    return () => window.removeEventListener('tf:logout', logout)
  }, [logout])

  const value = useMemo<AuthCtx>(() => ({
    user, loading, logout,
    async login(email, password) {
      const r = await api<{ access: string; refresh: string }>('/auth/login/', { method: 'POST', body: { email, password }, auth: false })
      tokens.set(r.access, r.refresh)
      setUser(await api<User>('/auth/me/'))
    },
    async register(data) {
      const r = await api<{ access: string; refresh: string; user: User; workspace: { slug: string } | null }>('/auth/register/', { method: 'POST', body: data, auth: false })
      tokens.set(r.access, r.refresh)
      setUser(r.user)
      return r.workspace?.slug ?? null
    },
  }), [user, loading, logout])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
