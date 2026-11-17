import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, downloadFile } from '../api/client'
import type { Attachment, AuditEntry, Comment, Issue, Label, Member, Paged, Sprint, Status } from '../api/types'
import { useWs } from '../layout/WorkspaceContext'
import {
  Avatar, Button, ConfirmButton, ErrorBox, Field, Loading, TypeIcon, errMsg, renderMentions, timeAgo, useToast,
} from './ui'

export default function IssueDrawer({ issueId, onClose }: { issueId: number; onClose: () => void; onNavigate?: (p: string) => void }) {
  const { p, can } = useWs()
  const qc = useQueryClient()
  const toast = useToast()
  const canEdit = can('member')
  const [tab, setTab] = useState<'comments' | 'attachments' | 'history'>('comments')

  const issueQ = useQuery({ queryKey: ['issue', p(''), issueId], queryFn: () => api<Issue>(p(`/issues/${issueId}/`)) })
  const issue = issueQ.data
  const transitions = useQuery({ queryKey: ['transitions', issueId, issue?.status], enabled: !!issue, queryFn: () => api<Status[]>(p(`/issues/${issueId}/transitions/`)) })
  const members = useQuery({ queryKey: ['members', p('')], queryFn: () => api<Member[]>(p('/members/')) })
  const labels = useQuery({ queryKey: ['labels', p('')], queryFn: () => api<Label[]>(p('/labels/')) })
  const sprints = useQuery({ queryKey: ['sprints', issue?.project], enabled: !!issue, queryFn: () => api<Paged<Sprint>>(p('/sprints/'), { params: { project: issue!.project } }) })
  const statuses = useQuery({ queryKey: ['statuses', issue?.project], enabled: !!issue, queryFn: () => api<Status[]>(p('/statuses/'), { params: { project: issue!.project } }) })

  const [title, setTitle] = useState('')
  const [desc, setDesc] = useState('')
  const [editingDesc, setEditingDesc] = useState(false)
  useEffect(() => { if (issue) { setTitle(issue.title); setDesc(issue.description) } }, [issue?.id, issue?.title, issue?.description])

  const invalidate = () => {
    for (const k of ['issue', 'board', 'issues', 'sprints', 'dashboard', 'history', 'projects']) qc.invalidateQueries({ queryKey: [k] })
  }
  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<Issue>(p(`/issues/${issueId}/`), { method: 'PATCH', body }),
    onSuccess: (i) => { qc.setQueryData(['issue', p(''), issueId], i); invalidate() },
    onError: (e) => { toast(errMsg(e), true); invalidate() },
  })
  const del = useMutation({
    mutationFn: () => api(p(`/issues/${issueId}/`), { method: 'DELETE' }),
    onSuccess: () => { invalidate(); toast('Issue deleted'); onClose() },
    onError: (e) => toast(errMsg(e), true),
  })

  if (issueQ.isLoading) return <Shell onClose={onClose}><Loading /></Shell>
  if (!issue) return <Shell onClose={onClose}><div className="empty">Issue not found.</div></Shell>

  const labelIds = new Set(issue.labels)
  const statusChoices = [issue.status_detail, ...(transitions.data ?? [])]
  const openSprints = (sprints.data?.results ?? []).filter((s) => s.state !== 'closed' || s.id === issue.sprint)

  return (
    <Shell onClose={onClose}>
      <div className="row spread" style={{ padding: '14px 24px 0' }}>
        <div className="row"><TypeIcon type={issue.type} /><span className="mono muted">{issue.key}</span></div>
        <div className="row">
          <Button variant="ghost" size="sm" onClick={() => { navigator.clipboard?.writeText(`${location.origin}/w/${p('').split('/')[2]}/issues/${issue.id}`); toast('Link copied') }}>🔗 Copy link</Button>
          {can('admin') && <ConfirmButton variant="danger" size="sm" message={`Delete ${issue.key}? This cannot be undone.`} onConfirm={() => del.mutate()}>Delete</ConfirmButton>}
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">✕</Button>
        </div>
      </div>
      <div className="drawer-grid">
        <div className="col gap-16" style={{ minWidth: 0 }}>
          <input className="title-input" value={title} disabled={!canEdit} aria-label="Title" onChange={(e) => setTitle(e.target.value)}
            onBlur={() => { if (title.trim() && title !== issue.title) patch.mutate({ title }); else setTitle(issue.title) }}
            onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
          <div>
            <h3 className="muted" style={{ marginBottom: 6 }}>Description</h3>
            {editingDesc && canEdit ? (
              <div className="col">
                <textarea className="textarea" rows={6} autoFocus value={desc} onChange={(e) => setDesc(e.target.value)} />
                <div className="row"><Button variant="primary" size="sm" onClick={() => { patch.mutate({ description: desc }); setEditingDesc(false) }}>Save</Button>
                  <Button size="sm" onClick={() => { setDesc(issue.description); setEditingDesc(false) }}>Cancel</Button></div>
              </div>
            ) : (
              <div onClick={() => canEdit && setEditingDesc(true)} style={{ whiteSpace: 'pre-wrap', minHeight: 40, padding: 8, borderRadius: 6, cursor: canEdit ? 'text' : 'default' }} className={canEdit ? 'desc-view' : ''}>
                {issue.description || <span className="faint">{canEdit ? 'Click to add a description…' : 'No description'}</span>}
              </div>
            )}
          </div>
          <div>
            <div className="tabs">
              {(['comments', 'attachments', 'history'] as const).map((t) => (
                <button key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
                  {t[0].toUpperCase() + t.slice(1)}{t === 'comments' && issue.comment_count ? ` (${issue.comment_count})` : ''}{t === 'attachments' && issue.attachment_count ? ` (${issue.attachment_count})` : ''}
                </button>))}
            </div>
            {tab === 'comments' && <Comments issueId={issue.id} members={members.data ?? []} onChange={invalidate} />}
            {tab === 'attachments' && <Attachments issueId={issue.id} onChange={invalidate} />}
            {tab === 'history' && <History issueId={issue.id} />}
          </div>
        </div>

        <aside className="props" aria-label="Issue properties">
          <Field label="Status">
            <select className="select" disabled={!canEdit} value={issue.status} onChange={(e) => patch.mutate({ status: Number(e.target.value) })}>
              {statusChoices.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
          <Field label="Assignee">
            <select className="select" disabled={!canEdit} value={issue.assignee ?? ''} onChange={(e) => patch.mutate({ assignee: e.target.value ? Number(e.target.value) : null })}>
              <option value="">Unassigned</option>
              {members.data?.map((m) => <option key={m.user.id} value={m.user.id}>{m.user.display_name}</option>)}
            </select>
          </Field>
          <div className="small muted">Reporter: <span className="row" style={{ display: 'inline-flex' }}><Avatar user={issue.reporter_detail} size="sm" /> {issue.reporter_detail?.display_name ?? '-'}</span></div>
          <Field label="Priority">
            <select className="select" disabled={!canEdit} value={issue.priority} onChange={(e) => patch.mutate({ priority: e.target.value })}>
              {['highest', 'high', 'medium', 'low', 'lowest'].map((x) => <option key={x}>{x}</option>)}
            </select>
          </Field>
          <Field label="Type">
            <select className="select" disabled={!canEdit} value={issue.type} onChange={(e) => patch.mutate({ type: e.target.value })}>
              {['task', 'bug', 'story', 'epic'].map((x) => <option key={x}>{x}</option>)}
            </select>
          </Field>
          <Field label="Story points">
            <input className="input" type="number" min={0} max={100} disabled={!canEdit} defaultValue={issue.story_points ?? ''} key={issue.story_points ?? 'n'}
              onBlur={(e) => { const v = e.target.value === '' ? null : Number(e.target.value); if (v !== issue.story_points) patch.mutate({ story_points: v }) }} />
          </Field>
          <Field label="Sprint">
            <select className="select" disabled={!canEdit} value={issue.sprint ?? ''} onChange={(e) => patch.mutate({ sprint: e.target.value ? Number(e.target.value) : null })}>
              <option value="">Backlog</option>
              {openSprints.map((s) => <option key={s.id} value={s.id}>{s.name}{s.state === 'active' ? ' (active)' : ''}</option>)}
            </select>
          </Field>
          <Field label="Due date">
            <input className="input" type="date" disabled={!canEdit} value={issue.due_date ?? ''} onChange={(e) => patch.mutate({ due_date: e.target.value || null })} />
          </Field>
          <Field label="Labels" group>
            <div className="row wrap" style={{ gap: 4 }}>
              {labels.data?.map((l) => (
                <button key={l.id} disabled={!canEdit} className="label-chip" style={{ background: l.color, opacity: labelIds.has(l.id) ? 1 : .3, border: 0, cursor: canEdit ? 'pointer' : 'default' }}
                  onClick={() => patch.mutate({ labels: labelIds.has(l.id) ? issue.labels.filter((x) => x !== l.id) : [...issue.labels, l.id] })}>{l.name}</button>))}
              {!labels.data?.length && <span className="small faint">No labels yet</span>}
            </div>
          </Field>
          {statuses.data && <div className="small faint">Workflow: {statuses.data.map((s) => s.name).join(' → ')}</div>}
          <div className="small faint">Created {timeAgo(issue.created_at)}{issue.resolved_at && ` · resolved ${timeAgo(issue.resolved_at)}`}</div>
        </aside>
      </div>
    </Shell>
  )
}

function Shell({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  useEffect(() => { const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }; document.addEventListener('keydown', h); return () => document.removeEventListener('keydown', h) }, [onClose])
  return <div className="drawer-bg" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}><aside className="drawer" role="dialog" aria-modal="true" aria-label="Issue details">{children}</aside></div>
}

function Comments({ issueId, members, onChange }: { issueId: number; members: Member[]; onChange: () => void }) {
  const { p, can } = useWs()
  const qc = useQueryClient()
  const [body, setBody] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)
  const q = useQuery({ queryKey: ['comments', issueId], queryFn: () => api<Comment[]>(p('/comments/'), { params: { issue: issueId } }) })
  const add = useMutation({
    mutationFn: () => api(p('/comments/'), { method: 'POST', body: { issue: issueId, body } }),
    onSuccess: () => { setBody(''); qc.invalidateQueries({ queryKey: ['comments', issueId] }); onChange() },
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(p(`/comments/${id}/`), { method: 'DELETE' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['comments', issueId] }); onChange() },
  })
  const handles = members.map((m) => m.user.email.split('@')[0])
  const tail = body.match(/@([A-Za-z0-9._+-]*)$/)
  const suggestions = tail ? handles.filter((h) => h.toLowerCase().startsWith(tail[1].toLowerCase()) && h.toLowerCase() !== tail[1].toLowerCase()).slice(0, 5) : []
  return (
    <div className="col gap-12">
      {q.isLoading && <Loading />}
      {q.data?.map((c) => (
        <div key={c.id} className="comment">
          <Avatar user={c.author_detail} size="lg" />
          <div className="bubble">
            <div className="row spread small"><strong>{c.author_detail?.display_name ?? 'Deleted user'}</strong>
              <span className="faint">{timeAgo(c.created_at)} {can('member') && <button className="btn ghost sm" onClick={() => window.confirm('Delete comment?') && remove.mutate(c.id)} aria-label="Delete comment">🗑</button>}</span></div>
            <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{renderMentions(c.body)}</div>
          </div>
        </div>))}
      {q.data && !q.data.length && <div className="small faint">No comments yet.</div>}
      {remove.isError && <ErrorBox error={remove.error} />}
      {can('member') ? (
        <form className="col" onSubmit={(e: FormEvent) => { e.preventDefault(); if (body.trim()) add.mutate() }}>
          <textarea ref={ref} className="textarea" placeholder="Add a comment… use @name to mention a teammate" value={body} onChange={(e) => setBody(e.target.value)}
            onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); if (body.trim()) add.mutate() } }} />
          {suggestions.length > 0 && <div className="row wrap small">Mention: {suggestions.map((h) => <button type="button" key={h} className="btn sm" onClick={() => { setBody(body.replace(/@([A-Za-z0-9._+-]*)$/, `@${h} `)); ref.current?.focus() }}>@{h}</button>)}</div>}
          {add.isError && <ErrorBox error={add.error} />}
          <div className="row"><Button variant="primary" size="sm" disabled={add.isPending || !body.trim()}>Comment</Button><span className="small faint">Ctrl+Enter to send</span></div>
        </form>
      ) : <div className="small faint">Viewers can read but not comment.</div>}
    </div>
  )
}

function fmtSize(n: number) { return n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB` }

function Attachments({ issueId, onChange }: { issueId: number; onChange: () => void }) {
  const { p, can } = useWs()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['attachments', issueId], queryFn: () => api<Attachment[]>(p('/attachments/'), { params: { issue: issueId } }) })
  const upload = useMutation({
    mutationFn: (f: File) => { const form = new FormData(); form.append('issue', String(issueId)); form.append('file', f); return api(p('/attachments/'), { method: 'POST', form }) },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['attachments', issueId] }); onChange(); qc.invalidateQueries({ queryKey: ['billing'] }); toast('File uploaded') },
    onError: (e: any) => { if (!e?.isPlanLimit) toast(errMsg(e), true) },
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(p(`/attachments/${id}/`), { method: 'DELETE' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['attachments', issueId] }); onChange() },
    onError: (e) => toast(errMsg(e), true),
  })
  return (
    <div className="col gap-12">
      {q.data?.map((a) => (
        <div key={a.id} className="row card" style={{ padding: '8px 12px' }}>
          <span>📎</span>
          <button className="btn ghost sm grow" style={{ justifyContent: 'flex-start' }} onClick={() => downloadFile(a.download_url, a.name).catch((e) => toast(errMsg(e), true))}>{a.name}</button>
          <span className="small faint">{fmtSize(a.size)} · {a.uploaded_by_detail?.display_name}</span>
          {can('member') && <ConfirmButton size="sm" variant="ghost" message="Delete this file?" onConfirm={() => remove.mutate(a.id)} aria-label="Delete attachment">🗑</ConfirmButton>}
        </div>))}
      {q.data && !q.data.length && <div className="small faint">No attachments.</div>}
      {can('member') && (
        <label className="btn" style={{ alignSelf: 'flex-start' }}>
          {upload.isPending ? 'Uploading…' : '+ Attach file'}
          <input type="file" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = '' }} />
        </label>)}
    </div>
  )
}

function fmtVal(v: unknown) { return v === null || v === undefined || v === '' ? '∅' : typeof v === 'object' ? JSON.stringify(v) : String(v) }

function History({ issueId }: { issueId: number }) {
  const { p } = useWs()
  const q = useQuery({ queryKey: ['history', issueId], queryFn: () => api<AuditEntry[]>(p(`/issues/${issueId}/history/`)) })
  if (q.isLoading) return <Loading />
  if (!q.data?.length) return <div className="small faint">No history yet.</div>
  return (
    <div className="col">
      {q.data.map((h) => (
        <div key={h.id} className="small" style={{ borderLeft: '2px solid var(--border-strong)', paddingLeft: 10 }}>
          <strong>{h.actor_name}</strong> {h.action === 'create' ? 'created this issue' : h.action === 'delete' ? 'deleted this issue' : 'updated'}{' '}
          <span className="faint">{timeAgo(h.created_at)}</span>
          {h.action === 'update' && Object.entries(h.changes).map(([k, v]: [string, any]) => (
            <div key={k} className="muted">• {k.replace(/_/g, ' ')}: <s className="faint">{fmtVal(v?.old)}</s> → <strong>{fmtVal(v?.new)}</strong></div>))}
        </div>))}
    </div>
  )
}
