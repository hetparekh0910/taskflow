import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Workspace } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Button, ErrorBox, Loading, RoleBadge } from '../components/ui'

/** Landing after login: jump straight into the last workspace, or pick/create one. */
export default function Home() {
  const { user, logout } = useAuth()
  const nav = useNavigate()
  const [sp] = useSearchParams()
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['workspaces'], queryFn: () => api<Workspace[]>('/workspaces/') })
  const [name, setName] = useState('')
  const [err, setErr] = useState<unknown>(null)

  if (isLoading) return <Loading />
  const last = localStorage.getItem('tf_last_ws')
  // Straight into the last-used (or first) workspace; the picker only shows for "+ New workspace" or no memberships.
  const target = sp.get('new') ? null : (data?.find((w) => w.slug === last) ?? data?.[0] ?? null)
  if (target) return <Navigate to={`/w/${target.slug}`} replace />

  async function create(e: FormEvent) {
    e.preventDefault()
    try {
      const w = await api<Workspace>('/workspaces/', { method: 'POST', body: { name } })
      qc.invalidateQueries({ queryKey: ['workspaces'] })
      nav(`/w/${w.slug}`)
    } catch (x) { setErr(x) }
  }
  return (
    <div className="center" style={{ minHeight: '100%', padding: 24 }}>
      <div className="card pad col gap-12" style={{ width: 440 }}>
        <h1>Choose a workspace</h1>
        <div className="muted">Signed in as {user?.email}</div>
        {data?.map((w) => (
          <button key={w.id} className="nav-item card" style={{ padding: 12 }} onClick={() => nav(`/w/${w.slug}`)}>
            <strong>{w.name}</strong><span className="badge">{w.plan}</span><span style={{ marginLeft: 'auto' }}><RoleBadge role={w.role} /></span>
          </button>
        ))}
        <form className="row" onSubmit={create}>
          <input className="input" placeholder="New workspace name" value={name} onChange={(e) => setName(e.target.value)} required />
          <Button variant="primary">Create</Button>
        </form>
        {!!err && <ErrorBox error={err} />}
        <Button variant="ghost" onClick={logout}>Sign out</Button>
      </div>
    </div>
  )
}
