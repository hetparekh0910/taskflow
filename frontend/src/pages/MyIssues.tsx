import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Issue, Paged } from '../api/types'
import IssueDrawer from '../components/IssueDrawer'
import { Empty, ErrorBox, Loading, PriorityMark, TypeIcon, formatDate } from '../components/ui'
import { useWs } from '../layout/WorkspaceContext'

export default function MyIssues() {
  const { p, slug, projects } = useWs()
  const [open, setOpen] = useState<number | null>(null)
  const [done, setDone] = useState(false)
  const [q, setQ] = useState('')
  const { data, isLoading, error } = useQuery({ queryKey: ['issues', slug, 'mine', done, q], queryFn: () => api<Paged<Issue>>(p('/issues/'), { params: { assignee: 'me', q, ordering: 'due_date' } }) })
  if (isLoading) return <Loading />
  if (error) return <ErrorBox error={error} />
  const rows = (data?.results ?? []).filter((i) => done || i.status_detail.category !== 'done')
  const key = (id: number) => projects.find((x) => x.id === id)?.key
  return (
    <>
      <div className="page-head"><h1>My issues</h1>
        <div className="row"><input className="input sm" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
          <label className="row small muted"><input type="checkbox" checked={done} onChange={(e) => setDone(e.target.checked)} /> Show done</label></div></div>
      {!rows.length ? <Empty title="Nothing assigned to you">Pick something from a <Link to={`/w/${slug}/projects`}>project board</Link>.</Empty> : (
        <div className="card"><table className="table"><thead><tr><th>Key</th><th>Title</th><th>Status</th><th>Priority</th><th>Due</th></tr></thead><tbody>
          {rows.map((i) => <tr key={i.id} style={{ cursor: 'pointer' }} onClick={() => setOpen(i.id)}>
            <td className="mono"><TypeIcon type={i.type} /> {key(i.project)}-{i.number}</td><td>{i.title}</td>
            <td><span className="badge"><span className="dot" style={{ background: i.status_detail.color }} />{i.status_detail.name}</span></td>
            <td><PriorityMark p={i.priority} /> {i.priority}</td><td>{formatDate(i.due_date)}</td></tr>)}</tbody></table></div>)}
      {open && <IssueDrawer issueId={open} onClose={() => setOpen(null)} />}
    </>
  )
}
