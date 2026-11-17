import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Notification, Paged, Project, Role, Workspace } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import CreateIssueModal from '../components/CreateIssueModal'
import { Avatar, Button, Loading, Menu, Modal, RoleBadge, timeAgo } from '../components/ui'
import { WorkspaceContext, makeCan } from './WorkspaceContext'

export default function AppShell() {
  const { slug = '' } = useParams()
  const nav = useNavigate()
  const { user, logout } = useAuth()
  const qc = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [palette, setPalette] = useState(false)
  const [limit, setLimit] = useState<any>(null)

  const wsQ = useQuery({ queryKey: ['ws', slug], queryFn: () => api<Workspace>(`/w/${slug}/`), retry: false })
  const all = useQuery({ queryKey: ['workspaces'], queryFn: () => api<Workspace[]>('/workspaces/') })
  const projQ = useQuery({ queryKey: ['projects', slug], enabled: !!wsQ.data, queryFn: () => api<Paged<Project>>(`/w/${slug}/projects/`, { params: { archived: false } }) })

  useEffect(() => { if (wsQ.data) localStorage.setItem('tf_last_ws', slug) }, [wsQ.data, slug])
  // Switching workspace must never show the previous tenant's cached data.
  const prev = useRef(slug)
  useEffect(() => { if (prev.current !== slug) { qc.removeQueries({ predicate: (q) => !['workspaces'].includes(String(q.queryKey[0])) && !q.queryKey.includes(slug) }); prev.current = slug } }, [slug, qc])

  useEffect(() => {
    const onLimit = (e: Event) => setLimit((e as CustomEvent).detail)
    window.addEventListener('tf:planlimit', onLimit)
    return () => window.removeEventListener('tf:planlimit', onLimit)
  }, [])
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || t.isContentEditable) return
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette(true) }
      else if (e.key === '/') { e.preventDefault(); setPalette(true) }
      else if (e.key === 'c' && !e.metaKey && !e.ctrlKey) { e.preventDefault(); setCreating(true) }
    }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [])
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette(true) } }
    document.addEventListener('keydown', h); return () => document.removeEventListener('keydown', h)
  }, [])

  const ctx = useMemo(() => wsQ.data ? {
    ws: wsQ.data, role: (wsQ.data.role ?? 'viewer') as Role, slug, projects: projQ.data?.results ?? [],
    can: makeCan((wsQ.data.role ?? 'viewer') as Role), p: (path: string) => `/w/${slug}${path}`,
  } : null, [wsQ.data, projQ.data, slug])

  if (wsQ.isLoading) return <Loading />
  if (wsQ.isError || !ctx) return (
    <div className="center"><div className="card pad col" style={{ textAlign: 'center' }}>
      <h2>Workspace not found</h2><div className="muted">It doesn't exist, or you're not a member.</div>
      <Button variant="primary" onClick={() => nav('/')}>Back to my workspaces</Button></div></div>
  )
  const { ws, can, projects } = ctx
  const toggleTheme = () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = next; localStorage.setItem('tf_theme', next)
  }
  return (
    <WorkspaceContext.Provider value={ctx}>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand"><span className="logo">T</span> TaskFlow</div>
          <Menu trigger={(_, t) => (
            <button className="nav-item card" onClick={t} style={{ padding: '8px 10px' }}>
              <strong style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{ws.name}</strong>
              <span className="badge" style={{ marginLeft: 'auto' }}>{ws.plan}</span>
            </button>)}>
            {(close) => <>
              {all.data?.map((w) => (
                <button key={w.id} className="nav-item" onClick={() => { close(); nav(`/w/${w.slug}`) }}>
                  {w.name}<span style={{ marginLeft: 'auto' }}><RoleBadge role={w.role} /></span>
                </button>))}
              <hr style={{ border: 0, borderTop: '1px solid var(--border)' }} />
              <button className="nav-item" onClick={() => { close(); nav('/?new=1') }}>+ New workspace…</button>
            </>}
          </Menu>
          <div className="nav-label">Workspace</div>
          <NavLink to={`/w/${slug}`} end className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>📊 Dashboard</NavLink>
          <NavLink to={`/w/${slug}/my-issues`} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>🙋 My issues</NavLink>
          <NavLink to={`/w/${slug}/projects`} end className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>📁 All projects</NavLink>
          <NavLink to={`/w/${slug}/reports`} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>📈 Reports</NavLink>
          <div className="nav-label">Projects</div>
          {projects.map((pr) => (
            <NavLink key={pr.id} to={`/w/${slug}/projects/${pr.id}`} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <span className="badge" style={{ minWidth: 42, justifyContent: 'center' }}>{pr.key}</span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{pr.name}</span>
              <span className="count">{pr.open_issues}</span>
            </NavLink>))}
          <div className="nav-label">Manage</div>
          <NavLink to={`/w/${slug}/team`} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>👥 Team</NavLink>
          {can('admin') && <NavLink to={`/w/${slug}/webhooks`} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>🔗 Webhooks</NavLink>}
          {can('admin') && <NavLink to={`/w/${slug}/audit`} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>🧾 Audit log</NavLink>}
          <NavLink to={`/w/${slug}/billing`} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>💳 Billing</NavLink>
        </aside>
        <div className="main">
          <header className="topbar">
            <button className="search-btn" onClick={() => setPalette(true)}>🔍 <span className="grow" style={{ textAlign: 'left' }}>Search issues…</span><kbd>Ctrl K</kbd></button>
            <div className="grow" />
            {can('member') && <Button variant="primary" onClick={() => setCreating(true)}>+ Create</Button>}
            <Bell slug={slug} />
            <Button variant="ghost" size="icon" onClick={toggleTheme} title="Toggle dark mode" aria-label="Toggle dark mode">🌓</Button>
            <Menu align="right" trigger={(_, t) => <button className="btn ghost icon" onClick={t} aria-label="Account"><Avatar user={user} /></button>}>
              {(close) => <>
                <div style={{ padding: '8px 10px' }}><strong>{user?.display_name}</strong><div className="small muted">{user?.email}</div><div style={{ marginTop: 4 }}><RoleBadge role={ws.role} /></div></div>
                <button className="nav-item" onClick={() => { close(); logout() }}>Sign out</button>
              </>}
            </Menu>
          </header>
          <main className="content"><Outlet /></main>
        </div>
      </div>
      {creating && <CreateIssueModal onClose={() => setCreating(false)} />}
      {palette && <Palette slug={slug} onClose={() => setPalette(false)} />}
      {limit && (
        <Modal title="Plan limit reached" onClose={() => setLimit(null)}>
          <p>{limit.detail}</p>
          <div className="row" style={{ justifyContent: 'flex-end' }}>
            <Button onClick={() => setLimit(null)}>Not now</Button>
            <Button variant="primary" onClick={() => { setLimit(null); nav(`/w/${slug}/billing`) }}>See plans</Button>
          </div>
        </Modal>)}
    </WorkspaceContext.Provider>
  )
}

function Bell({ slug }: { slug: string }) {
  const nav = useNavigate()
  const qc = useQueryClient()
  const count = useQuery({ queryKey: ['unread', slug], refetchInterval: 30_000, queryFn: () => api<{ count: number }>(`/w/${slug}/notifications/unread_count/`) })
  const list = useQuery({ queryKey: ['notifications', slug], queryFn: () => api<Notification[]>(`/w/${slug}/notifications/`) })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['unread', slug] }); qc.invalidateQueries({ queryKey: ['notifications', slug] }) }
  return (
    <Menu align="right" trigger={(_, t) => (
      <button className="btn ghost icon bell" onClick={() => { t(); list.refetch() }} aria-label="Notifications">🔔
        {!!count.data?.count && <span className="pip">{count.data.count}</span>}</button>)}>
      {(close) => (
        <div style={{ width: 340, maxHeight: 420, overflowY: 'auto' }}>
          <div className="row spread" style={{ padding: '6px 10px' }}><strong>Notifications</strong>
            <button className="btn sm ghost" onClick={async () => { await api(`/w/${slug}/notifications/mark_all_read/`, { method: 'POST' }); refresh() }}>Mark all read</button></div>
          {!list.data?.length && <div className="empty small">You're all caught up 🎉</div>}
          {list.data?.map((n) => (
            <button key={n.id} className="nav-item" style={{ alignItems: 'flex-start', opacity: n.read ? .6 : 1 }}
              onClick={async () => { close(); if (!n.read) { await api(`/w/${slug}/notifications/${n.id}/`, { method: 'PATCH', body: { read: true } }); refresh() } if (n.issue) nav(`/w/${slug}/issues/${n.issue}`) }}>
              {!n.read && <span className="dot" style={{ background: 'var(--accent)', marginTop: 6 }} />}
              <span className="col" style={{ gap: 0 }}><span>{n.message}</span><span className="small faint">{timeAgo(n.created_at)}</span></span>
            </button>))}
        </div>)}
    </Menu>
  )
}

function Palette({ slug, onClose }: { slug: string; onClose: () => void }) {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const res = useQuery({ queryKey: ['search', slug, q], enabled: q.length >= 2, queryFn: () => api<{ issues: { id: number; key: string; title: string; status: string }[]; projects: { id: number; key: string; name: string }[] }>(`/w/${slug}/search/`, { params: { q } }) })
  const items = [
    ...(res.data?.projects ?? []).map((p) => ({ k: `p${p.id}`, label: `${p.key} · ${p.name}`, sub: 'Project', go: `/w/${slug}/projects/${p.id}` })),
    ...(res.data?.issues ?? []).map((i) => ({ k: `i${i.id}`, label: `${i.key}  ${i.title}`, sub: i.status, go: `/w/${slug}/issues/${i.id}` })),
  ]
  const go = (i: number) => { const it = items[i]; if (it) { onClose(); nav(it.go) } }
  return (
    <Modal onClose={onClose}>
      <div className="palette" style={{ margin: -20 }}>
        <input className="input" autoFocus placeholder="Search issues by title or key (e.g. WEB-12)…" value={q}
          onChange={(e) => { setQ(e.target.value); setSel(0) }}
          onKeyDown={(e) => { if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, items.length - 1)) } else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)) } else if (e.key === 'Enter') go(sel) }} />
        <div style={{ padding: 8, minHeight: 80 }}>
          {q.length < 2 && <div className="small faint" style={{ padding: 12 }}>Type at least 2 characters. Shortcuts: <kbd>c</kbd> create issue · <kbd>/</kbd> search</div>}
          {q.length >= 2 && !items.length && !res.isFetching && <div className="small faint" style={{ padding: 12 }}>No results.</div>}
          {items.map((it, i) => (
            <div key={it.k} className={`item ${i === sel ? 'sel' : ''}`} onMouseEnter={() => setSel(i)} onClick={() => go(i)}>
              <span className="grow">{it.label}</span><span className="badge">{it.sub}</span></div>))}
        </div>
      </div>
    </Modal>
  )
}
