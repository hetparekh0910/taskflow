import { useEffect, useMemo, useState } from 'react'
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  DndContext, DragOverlay, PointerSensor, KeyboardSensor, closestCorners, useDroppable, useSensor, useSensors,
  type DragEndEvent, type DragStartEvent,
} from '@dnd-kit/core'
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { api } from '../api/client'
import type { Board as BoardT, BoardColumn, Issue, Member } from '../api/types'
import CreateIssueModal from '../components/CreateIssueModal'
import { IssueCardBody } from '../components/IssueCard'
import { applyMove, planMove } from '../lib/boardMove'
import IssueDrawer from '../components/IssueDrawer'
import { Button, ErrorBox, Loading, errMsg, useToast } from '../components/ui'
import { useWs } from '../layout/WorkspaceContext'

/** /w/:slug/issues/:id  ->  open that issue on its project's board (shareable deep link). */
export function IssueRedirect() {
  const { issueId } = useParams()
  const { p, slug } = useWs()
  const { data, isError } = useQuery({ queryKey: ['issue-lookup', slug, issueId], queryFn: () => api<Issue>(p(`/issues/${issueId}/`)) })
  if (isError) return <div className="empty">Issue not found.</div>
  if (!data) return <Loading />
  return <Navigate to={`/w/${slug}/projects/${data.project}?issue=${data.id}`} replace />
}

const cardId = (id: number) => `issue:${id}`
const colId = (id: number) => `col:${id}`

function SortableCard({ issue, disabled, onOpen }: { issue: Issue; disabled: boolean; onOpen: () => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: cardId(issue.id), disabled })
  return (
    <div ref={setNodeRef} className={`issue-card ${isDragging ? 'dragging' : ''}`} style={{ transform: CSS.Transform.toString(transform), transition, cursor: disabled ? 'pointer' : undefined }}
      {...attributes} {...listeners} data-testid={`card-${issue.key}`}>
      <IssueCardBody issue={issue} onOpen={onOpen} />
    </div>
  )
}

function Column({ col, dragging, active, canEdit, onOpen, onAdd }: {
  col: BoardColumn; dragging: BoardColumn | null; active: boolean; canEdit: boolean; onOpen: (i: Issue) => void; onAdd: () => void
}) {
  const { setNodeRef, isOver } = useDroppable({ id: colId(col.status.id) })
  const full = col.wip_limit != null && col.issues.length >= col.wip_limit
  const blocked = !!dragging && dragging.status.id !== col.status.id && !dragging.allowed_to.includes(col.status.id)
  return (
    <section className={`column ${isOver && !blocked ? 'over' : ''} ${blocked ? 'blocked' : ''}`} aria-label={col.status.name}>
      <div className="column-head">
        <span className="dot" style={{ background: col.status.color }} />
        <span>{col.status.name}</span>
        <span className="n">{col.issues.length}{col.wip_limit != null && <span className={`wip ${full ? 'full' : ''}`}> / {col.wip_limit}</span>}</span>
        <span className="grow" />
        {canEdit && <button className="btn ghost sm" onClick={onAdd} title={`Add to ${col.status.name}`} aria-label={`Add issue to ${col.status.name}`}>＋</button>}
      </div>
      <div className="column-body" ref={setNodeRef}>
        <SortableContext items={col.issues.map((i) => cardId(i.id))} strategy={verticalListSortingStrategy}>
          {col.issues.map((i) => <SortableCard key={i.id} issue={i} disabled={!canEdit} onOpen={() => onOpen(i)} />)}
        </SortableContext>
        {!col.issues.length && <div className="small faint" style={{ textAlign: 'center', padding: 12 }}>{blocked ? 'Move not allowed by workflow' : 'Drop issues here'}</div>}
      </div>
    </section>
  )
}

export default function Board() {
  const { projectId } = useParams()
  const [sp, setSp] = useSearchParams()
  const { p, slug, can } = useWs()
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const canEdit = can('member')
  const [assignee, setAssignee] = useState('')
  const [q, setQ] = useState('')
  const [onlySprint, setOnlySprint] = useState(false)
  const [creatingIn, setCreatingIn] = useState<number | null | undefined>(undefined)
  const [dragIssue, setDragIssue] = useState<Issue | null>(null)
  const [cols, setCols] = useState<BoardColumn[]>([])

  const key = ['board', slug, projectId, assignee, q, onlySprint]
  const { data, isLoading, error } = useQuery({
    queryKey: key,
    queryFn: () => api<BoardT>(p(`/projects/${projectId}/board/`), { params: { assignee, q, sprint: onlySprint ? 'active' : undefined } }),
  })
  const members = useQuery({ queryKey: ['members', p('')], queryFn: () => api<Member[]>(p('/members/')) })
  useEffect(() => { if (data) setCols(data.columns) }, [data])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const move = useMutation({
    mutationFn: (v: { id: number; status: number; above: number | null; below: number | null }) =>
      api<Issue>(p(`/issues/${v.id}/move/`), { method: 'POST', body: { status: v.status, above: v.above, below: v.below } }),
    onError: (e) => { toast(errMsg(e), true); qc.invalidateQueries({ queryKey: ['board'] }) }, // revert optimistic move
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['board'] }); qc.invalidateQueries({ queryKey: ['dashboard'] }) },
  })

  const dragCol = useMemo(() => (dragIssue ? cols.find((c) => c.issues.some((i) => i.id === dragIssue.id)) ?? null : null), [dragIssue, cols])

  function onDragStart(e: DragStartEvent) {
    const id = Number(String(e.active.id).split(':')[1])
    setDragIssue(cols.flatMap((c) => c.issues).find((i) => i.id === id) ?? null)
  }

  function onDragEnd(e: DragEndEvent) {
    setDragIssue(null)
    const { active, over } = e
    if (!over || !canEdit) return
    const t = active.rect.current.translated
    const below = !!t && t.top > over.rect.top + over.rect.height / 2
    const plan = planMove(cols, Number(String(active.id).split(':')[1]), String(over.id), below)
    if (plan.kind === 'noop') return
    if (plan.kind === 'error') { toast(plan.message, true); return }
    setCols((prev) => applyMove(prev, plan)) // optimistic UI; the server re-validates everything
    move.mutate({ id: plan.activeId, status: plan.dst.status.id, above: plan.above, below: plan.below })
  }

  const openId = sp.get('issue') ? Number(sp.get('issue')) : null
  const setOpen = (id: number | null) => { const n = new URLSearchParams(sp); id ? n.set('issue', String(id)) : n.delete('issue'); setSp(n, { replace: true }) }

  if (isLoading) return <Loading />
  if (error || !data) return <ErrorBox error={error} />
  const proj = data.project
  const total = cols.reduce((n, c) => n + c.issues.length, 0)
  return (
    <>
      <div className="page-head">
        <div className="row gap-12">
          <h1>{proj.name}</h1><span className="badge">{proj.key}</span>
          {data.active_sprint && <span className="badge accent" title={data.active_sprint.goal}>🏃 {data.active_sprint.name}</span>}
        </div>
        <div className="row wrap">
          <Link className="btn" to={`/w/${slug}/projects/${proj.id}/backlog`}>Backlog &amp; sprints</Link>
          {can('admin') && <Link className="btn" to={`/w/${slug}/projects/${proj.id}/settings`}>⚙ Workflow</Link>}
          {canEdit && <Button variant="primary" onClick={() => setCreatingIn(null)}>+ Issue</Button>}
        </div>
      </div>
      <div className="row wrap" style={{ marginBottom: 12 }}>
        <input className="input sm" style={{ width: 220 }} placeholder="Filter this board…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter board" />
        <select className="select sm" value={assignee} onChange={(e) => setAssignee(e.target.value)} aria-label="Filter by assignee">
          <option value="">All assignees</option><option value="me">Assigned to me</option>
          {members.data?.map((m) => <option key={m.user.id} value={m.user.id}>{m.user.display_name}</option>)}
        </select>
        <label className="row small muted" style={{ gap: 4 }}><input type="checkbox" checked={onlySprint} onChange={(e) => setOnlySprint(e.target.checked)} /> Active sprint only</label>
        <span className="grow" /><span className="small faint">{total} issues{!canEdit && ' · read-only (viewer)'}</span>
      </div>
      <DndContext sensors={sensors} collisionDetection={closestCorners} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragCancel={() => setDragIssue(null)}>
        <div className="board">
          {cols.map((c) => <Column key={c.id} col={c} dragging={dragCol} active={!!dragIssue} canEdit={canEdit} onOpen={(i) => setOpen(i.id)} onAdd={() => setCreatingIn(c.status.id)} />)}
        </div>
        <DragOverlay>{dragIssue && <div className="issue-card overlay"><IssueCardBody issue={dragIssue} /></div>}</DragOverlay>
      </DndContext>
      {creatingIn !== undefined && <CreateIssueModal projectId={proj.id} statusId={creatingIn ?? undefined} sprintId={data.active_sprint?.id} onClose={() => setCreatingIn(undefined)} />}
      {openId && <IssueDrawer issueId={openId} onClose={() => setOpen(null)} onNavigate={(path) => nav(path)} />}
    </>
  )
}
