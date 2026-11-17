import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import type { Burndown, Issue, Paged, Project, Sprint } from '../api/types'
import CreateIssueModal from '../components/CreateIssueModal'
import IssueDrawer from '../components/IssueDrawer'
import { Avatar, Button, ConfirmButton, ErrorBox, Field, Loading, Modal, PriorityMark, TypeIcon, errMsg, formatDate, useToast } from '../components/ui'
import { useWs } from '../layout/WorkspaceContext'

export default function Backlog() {
  const { projectId } = useParams()
  const { p, slug, can } = useWs()
  const qc = useQueryClient()
  const toast = useToast()
  const [open, setOpen] = useState<number | null>(null)
  const [creating, setCreating] = useState<{ sprint: number | null } | null>(null)
  const [newSprint, setNewSprint] = useState(false)
  const [closing, setClosing] = useState<Sprint | null>(null)

  const project = useQuery({ queryKey: ['project', slug, projectId], queryFn: () => api<Project>(p(`/projects/${projectId}/`)) })
  const sprints = useQuery({ queryKey: ['sprints', Number(projectId)], queryFn: () => api<Paged<Sprint>>(p('/sprints/'), { params: { project: projectId } }) })
  const issues = useQuery({ queryKey: ['issues', slug, 'backlog', projectId], queryFn: () => api<Paged<Issue>>(p('/issues/'), { params: { project: projectId, ordering: 'rank' } }) })
  const refresh = () => { for (const k of ['sprints', 'issues', 'board', 'burndown', 'dashboard']) qc.invalidateQueries({ queryKey: [k] }) }
  const act = useMutation({
    mutationFn: (v: { path: string; body?: unknown }) => api(p(v.path), { method: 'POST', body: v.body }),
    onSuccess: () => { refresh(); toast('Done') }, onError: (e) => toast(errMsg(e), true),
  })
  const assign = useMutation({
    mutationFn: (v: { id: number; sprint: number | null }) => api(p(`/issues/${v.id}/`), { method: 'PATCH', body: { sprint: v.sprint } }),
    onSuccess: refresh, onError: (e) => toast(errMsg(e), true),
  })

  if (sprints.isLoading || issues.isLoading) return <Loading />
  if (sprints.error || issues.error) return <ErrorBox error={sprints.error ?? issues.error} />
  const all = issues.data?.results ?? []
  const live = (sprints.data?.results ?? []).filter((s) => s.state !== 'closed').sort((a, b) => (a.state === 'active' ? -1 : 1) - (b.state === 'active' ? -1 : 1) || a.id - b.id)
  const closedList = (sprints.data?.results ?? []).filter((s) => s.state === 'closed')
  const backlog = all.filter((i) => !i.sprint)
  const planned = live.filter((s) => s.state === 'planned')
  const active = live.find((s) => s.state === 'active')

  const Row = ({ i, sprintId }: { i: Issue; sprintId: number | null }) => (
    <div className="backlog-row" onClick={() => setOpen(i.id)}>
      <TypeIcon type={i.type} /><span className="mono muted" style={{ width: 70 }}>{i.key}</span>
      <span className="grow" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textDecoration: i.status_detail.category === 'done' ? 'line-through' : 'none' }}>{i.title}</span>
      <span className="badge"><span className="dot" style={{ background: i.status_detail.color }} />{i.status_detail.name}</span>
      <PriorityMark p={i.priority} />
      {i.story_points != null && <span className="points">{i.story_points}</span>}
      <Avatar user={i.assignee_detail} size="sm" />
      {can('member') && (
        <select className="select sm" aria-label={`Move ${i.key} to sprint`} value={sprintId ?? ''} onClick={(e) => e.stopPropagation()}
          onChange={(e) => assign.mutate({ id: i.id, sprint: e.target.value ? Number(e.target.value) : null })}>
          <option value="">Backlog</option>{live.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>)}
    </div>
  )

  const SprintBox = ({ s }: { s: Sprint }) => {
    const list = all.filter((i) => i.sprint === s.id)
    return (
      <div className="card sprint-box">
        <div className="head">
          <strong>{s.name}</strong>
          <span className={`badge ${s.state === 'active' ? 'success' : ''}`}>{s.state}</span>
          <span className="small muted">{s.start_date ? `${formatDate(s.start_date)} → ${formatDate(s.end_date)}` : 'No dates'} · {s.issue_count} issues · {s.done_points}/{s.total_points} pts</span>
          <span className="grow" />
          {can('member') && <Button size="sm" onClick={() => setCreating({ sprint: s.id })}>+ Issue</Button>}
          {can('admin') && s.state === 'planned' && <Button size="sm" variant="primary" disabled={!s.issue_count} title={!s.issue_count ? 'Add issues first' : ''} onClick={() => act.mutate({ path: `/sprints/${s.id}/start/` })}>Start sprint</Button>}
          {can('admin') && s.state === 'active' && <Button size="sm" variant="primary" onClick={() => setClosing(s)}>Complete sprint</Button>}
          {can('admin') && s.state === 'planned' && <ConfirmButton size="sm" variant="ghost" message="Delete this sprint? Issues return to the backlog." onConfirm={() => api(p(`/sprints/${s.id}/`), { method: 'DELETE' }).then(refresh).catch((e) => toast(errMsg(e), true))}>🗑</ConfirmButton>}
        </div>
        {s.goal && <div className="small muted" style={{ padding: '6px 14px', borderBottom: '1px solid var(--border)' }}>🎯 {s.goal}</div>}
        {list.map((i) => <Row key={i.id} i={i} sprintId={s.id} />)}
        {!list.length && <div className="small faint" style={{ padding: 14 }}>No issues in this sprint. Use the dropdown on a backlog item to plan it here.</div>}
      </div>
    )
  }

  return (
    <>
      <div className="page-head">
        <div className="row gap-12"><Link to={`/w/${slug}/projects/${projectId}`} className="btn ghost sm">← Board</Link><h1>{project.data?.name} · Backlog</h1></div>
        <div className="row">{can('admin') && <Button onClick={() => setNewSprint(true)}>+ New sprint</Button>}
          {can('member') && <Button variant="primary" onClick={() => setCreating({ sprint: null })}>+ Issue</Button>}</div>
      </div>
      {active && <BurndownCard sprint={active} />}
      {live.map((s) => <SprintBox key={s.id} s={s} />)}
      <div className="card sprint-box">
        <div className="head"><strong>Backlog</strong><span className="small muted">{backlog.length} issues · {backlog.reduce((n, i) => n + (i.story_points ?? 0), 0)} pts</span></div>
        {backlog.map((i) => <Row key={i.id} i={i} sprintId={null} />)}
        {!backlog.length && <div className="small faint" style={{ padding: 14 }}>The backlog is empty.</div>}
      </div>
      {closedList.length > 0 && (
        <details className="card pad"><summary style={{ cursor: 'pointer', fontWeight: 600 }}>Completed sprints ({closedList.length})</summary>
          <table className="table"><thead><tr><th>Sprint</th><th>Dates</th><th>Committed</th><th>Completed</th></tr></thead><tbody>
            {closedList.map((s) => <tr key={s.id}><td>{s.name}</td><td>{formatDate(s.start_date)} → {formatDate(s.end_date)}</td><td>{s.committed_points} pts</td><td>{s.completed_points} pts</td></tr>)}</tbody></table></details>)}
      {newSprint && <NewSprint projectId={Number(projectId)} path={p('/sprints/')} onClose={() => setNewSprint(false)} onDone={refresh} />}
      {closing && (
        <Modal title={`Complete ${closing.name}`} onClose={() => setClosing(null)}>
          <p className="muted">Finished issues stay in the sprint. Unfinished issues move to:</p>
          <CloseForm planned={planned} onSubmit={(target) => { act.mutate({ path: `/sprints/${closing.id}/close/`, body: { move_open_to: target } }); setClosing(null) }} />
        </Modal>)}
      {creating && <CreateIssueModal projectId={Number(projectId)} sprintId={creating.sprint} onClose={() => setCreating(null)} />}
      {open && <IssueDrawer issueId={open} onClose={() => setOpen(null)} />}
    </>
  )
}

function CloseForm({ planned, onSubmit }: { planned: Sprint[]; onSubmit: (t: number | null) => void }) {
  const [t, setT] = useState('')
  return (
    <div className="col gap-12">
      <select className="select" value={t} onChange={(e) => setT(e.target.value)}><option value="">Backlog</option>{planned.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
      <div className="row" style={{ justifyContent: 'flex-end' }}><Button variant="primary" onClick={() => onSubmit(t ? Number(t) : null)}>Complete sprint</Button></div>
    </div>
  )
}

function NewSprint({ projectId, path, onClose, onDone }: { projectId: number; path: string; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState(''); const [goal, setGoal] = useState(''); const [start, setStart] = useState(''); const [end, setEnd] = useState('')
  const m = useMutation({ mutationFn: () => api(path, { method: 'POST', body: { project: projectId, name, goal, start_date: start || null, end_date: end || null } }), onSuccess: () => { onDone(); onClose() } })
  return (
    <Modal title="New sprint" onClose={onClose}>
      <form className="col gap-12" onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate() }}>
        {m.isError && <ErrorBox error={m.error} />}
        <Field label="Name"><input className="input" required autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Sprint 4" /></Field>
        <Field label="Goal"><input className="input" value={goal} onChange={(e) => setGoal(e.target.value)} /></Field>
        <div className="row"><Field label="Start"><input className="input" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field><Field label="End"><input className="input" type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field></div>
        <div className="row" style={{ justifyContent: 'flex-end' }}><Button type="button" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={m.isPending}>Create</Button></div>
      </form>
    </Modal>
  )
}

function BurndownCard({ sprint }: { sprint: Sprint }) {
  const { p } = useWs()
  const { data } = useQuery({ queryKey: ['burndown', sprint.id, sprint.done_points], queryFn: () => api<Burndown>(p(`/sprints/${sprint.id}/burndown/`)) })
  if (!data?.days.length) return null
  return (
    <div className="card pad" style={{ marginBottom: 16 }}>
      <div className="row spread"><h3>Burndown · {sprint.name}</h3><span className="small muted">{sprint.done_points} of {data.total_points} points done</span></div>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data.days.map((d) => ({ ...d, label: d.date.slice(5) }))}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" /><XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--text-2)' }} /><YAxis tick={{ fill: 'var(--text-2)' }} /><Tooltip /><Legend />
          <Line type="linear" dataKey="ideal" stroke="#94a3b8" strokeDasharray="5 5" dot={false} name="Ideal" />
          <Line type="stepAfter" dataKey="remaining" stroke="#6366f1" strokeWidth={2} name="Remaining" connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
