import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { AuditEntry, Paged } from '../api/types'
import { Empty, ErrorBox, Loading, timeAgo } from '../components/ui'
import { useWs } from '../layout/WorkspaceContext'

const fmt = (v: unknown) => (v === null || v === undefined || v === '' ? '∅' : typeof v === 'object' ? JSON.stringify(v) : String(v))
const MODELS = ['Issue', 'Project', 'Sprint', 'Comment', 'Attachment', 'WorkflowStatus', 'WorkflowTransition', 'Label', 'Membership', 'Webhook']

export default function Audit() {
  const { p, can, slug } = useWs()
  const [model, setModel] = useState(''); const [action, setAction] = useState(''); const [q, setQ] = useState(''); const [page, setPage] = useState(1)
  const { data, isLoading, error } = useQuery({ queryKey: ['audit', slug, model, action, q, page], enabled: can('admin'), placeholderData: (x) => x,
    queryFn: () => api<Paged<AuditEntry>>(p('/audit-log/'), { params: { model, action, search: q, page } }) })
  if (!can('admin')) return <div className="empty">Only admins can view the audit log.</div>
  if (error) return <ErrorBox error={error} />
  return (
    <>
      <div className="page-head"><div><h1>Audit log</h1><div className="muted">Every create, update and delete, recorded automatically. Read-only.</div></div>
        <div className="row wrap"><input className="input sm" placeholder="Search…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
          <select className="select sm" value={model} onChange={(e) => { setModel(e.target.value); setPage(1) }} aria-label="Model"><option value="">All objects</option>{MODELS.map((m) => <option key={m}>{m}</option>)}</select>
          <select className="select sm" value={action} onChange={(e) => { setAction(e.target.value); setPage(1) }} aria-label="Action"><option value="">All actions</option><option value="create">created</option><option value="update">updated</option><option value="delete">deleted</option></select></div></div>
      {isLoading ? <Loading /> : !data?.results.length ? <Empty title="No matching events" /> : (
        <div className="card"><table className="table"><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Object</th><th>Changes</th></tr></thead><tbody>
          {data.results.map((e) => <tr key={e.id}><td className="small muted" title={new Date(e.created_at).toLocaleString()}>{timeAgo(e.created_at)}</td><td>{e.actor_name}</td>
            <td><span className={`badge ${e.action === 'create' ? 'success' : e.action === 'delete' ? 'danger' : 'accent'}`}>{e.action}</span></td>
            <td><span className="badge">{e.model}</span> {e.object_repr}</td>
            <td className="small">{e.action === 'update' ? Object.entries(e.changes).map(([k, v]: [string, any]) => <div key={k}><span className="muted">{k.replace(/_/g, ' ')}:</span> <s className="faint">{fmt(v?.old)}</s> → <strong>{fmt(v?.new)}</strong></div>) : <span className="faint">-</span>}</td></tr>)}</tbody></table></div>)}
      <div className="row" style={{ justifyContent: 'center', marginTop: 12 }}>
        <button className="btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>← Newer</button><span className="small muted">Page {page} · {data?.count ?? 0} events</span>
        <button className="btn" disabled={!data || page * 100 >= data.count} onClick={() => setPage(page + 1)}>Older →</button></div>
    </>
  )
}
