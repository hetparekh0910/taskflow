import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, downloadFile } from '../api/client'
import type { Board, Project, Status, Transition } from '../api/types'
import { Button, ConfirmButton, ErrorBox, Field, Loading, errMsg, useToast } from '../components/ui'
import { useWs } from '../layout/WorkspaceContext'

export default function ProjectSettings() {
  const { projectId } = useParams()
  const { p, slug, can } = useWs()
  const qc = useQueryClient(); const toast = useToast(); const nav = useNavigate()
  const project = useQuery({ queryKey: ['project', slug, projectId], queryFn: () => api<Project>(p(`/projects/${projectId}/`)) })
  const statuses = useQuery({ queryKey: ['statuses', Number(projectId)], queryFn: () => api<Status[]>(p('/statuses/'), { params: { project: projectId } }) })
  const trans = useQuery({ queryKey: ['transitions-all', projectId], queryFn: () => api<Transition[]>(p('/transitions/'), { params: { project: projectId } }) })
  const board = useQuery({ queryKey: ['board', slug, projectId, '', '', false], queryFn: () => api<Board>(p(`/projects/${projectId}/board/`)) })
  const [name, setName] = useState(''); const [cat, setCat] = useState('in_progress'); const [color, setColor] = useState('#3b82f6')
  const refresh = () => { for (const k of ['statuses', 'transitions-all', 'board', 'transitions', 'project', 'projects']) qc.invalidateQueries({ queryKey: [k] }) }
  const run = (fn: () => Promise<unknown>) => fn().then(refresh).catch((e) => toast(errMsg(e), true))

    const add = useMutation({ mutationFn: () => api(p('/statuses/'), { method: 'POST', body: { project: Number(projectId), name, category: cat, color, order: sts.length } }), onSuccess: () => { setName(''); refresh() } })
  if (!can('admin')) return <div className="empty">Only admins can edit workflows.</div>
  if (statuses.isLoading || trans.isLoading) return <Loading />
  const sts = statuses.data ?? []; const tr = trans.data ?? []
  const has = (a: number, b: number) => tr.find((t) => t.from_status === a && t.to_status === b)
  const open = tr.length === 0
  const toggle = (a: number, b: number) => run(async () => {
    const ex = has(a, b)
    if (ex) await api(p(`/transitions/${ex.id}/`), { method: 'DELETE' })
    else await api(p('/transitions/'), { method: 'POST', body: { project: Number(projectId), from_status: a, to_status: b } })
  })
  return (
    <>
      <div className="page-head"><div className="row gap-12"><Link to={`/w/${slug}/projects/${projectId}`} className="btn ghost sm">← Board</Link><h1>{project.data?.name} · Workflow</h1></div>
        <ConfirmButton variant="danger" message="Archive this project? It will disappear from the sidebar." onConfirm={() => run(async () => { await api(p(`/projects/${projectId}/`), { method: 'PATCH', body: { archived: true } }); nav(`/w/${slug}`) })}>Archive project</ConfirmButton></div>
      <div className="grid two">
        <div className="card pad col gap-12"><h3>Statuses (board columns)</h3>
          {sts.map((s) => {
            const col = board.data?.columns.find((c) => c.status.id === s.id)
            return (
              <div key={s.id} className="row card" style={{ padding: '8px 12px' }}>
                <span className="dot" style={{ background: s.color }} /><strong className="grow">{s.name}</strong><span className="badge">{s.category.replace('_', ' ')}</span>
                {col && <label className="row small muted" title="Max issues in this column (empty = unlimited)">WIP
                  <input className="input sm" type="number" min={1} style={{ width: 60 }} defaultValue={col.wip_limit ?? ''} key={col.wip_limit ?? 'n'}
                    onBlur={(e) => { const v = e.target.value ? Number(e.target.value) : null; if (v !== col.wip_limit) run(() => api(p(`/columns/${col.id}/`), { method: 'PATCH', body: { wip_limit: v } })) }} /></label>}
                <ConfirmButton size="sm" variant="ghost" message={`Delete status "${s.name}"?`} onConfirm={() => run(() => api(p(`/statuses/${s.id}/`), { method: 'DELETE' }))}>🗑</ConfirmButton>
              </div>)})}
          <form className="row wrap" onSubmit={(e: FormEvent) => { e.preventDefault(); add.mutate() }}>
            <input className="input" style={{ flex: 1, minWidth: 140 }} placeholder="New status, e.g. QA" required value={name} onChange={(e) => setName(e.target.value)} />
            <select className="select" style={{ width: 130 }} value={cat} onChange={(e) => setCat(e.target.value)}><option value="todo">to do</option><option value="in_progress">in progress</option><option value="done">done</option></select>
            <input type="color" value={color} onChange={(e) => setColor(e.target.value)} aria-label="Colour" style={{ width: 36, height: 34, border: 0, background: 'none' }} />
            <Button variant="primary" disabled={add.isPending}>Add</Button>
          </form>
          {add.isError && <ErrorBox error={add.error} />}
        </div>
        <div className="card pad col gap-12"><div className="row spread"><h3>Allowed transitions</h3>
          <div className="row"><Button size="sm" onClick={() => run(() => api(p('/transitions/linear/'), { method: 'POST', body: { project: Number(projectId) } }))}>Linear preset</Button>
            <Button size="sm" disabled={open} onClick={() => run(() => api(p('/transitions/reset/'), { method: 'POST', body: { project: Number(projectId) } }))}>Allow all</Button></div></div>
          <div className={`badge ${open ? 'success' : 'warn'}`} style={{ alignSelf: 'flex-start' }}>{open ? 'Open workflow: any move is allowed' : 'Enforced: only ticked moves are allowed'}</div>
          <div style={{ overflowX: 'auto' }}><table className="table"><thead><tr><th>From ↓ / To →</th>{sts.map((s) => <th key={s.id}>{s.name}</th>)}</tr></thead><tbody>
            {sts.map((a) => <tr key={a.id}><td><strong>{a.name}</strong></td>{sts.map((b) => <td key={b.id} style={{ textAlign: 'center' }}>
              {a.id === b.id ? <span className="faint">-</span> : <input type="checkbox" checked={open ? true : !!has(a.id, b.id)} onChange={() => (open ? run(async () => {
                // leaving the open state: materialise every move except this one, so the click means "forbid"
                const pairs = sts.flatMap((x) => sts.filter((y) => y.id !== x.id).map((y) => [x.id, y.id])).filter(([x, y]) => !(x === a.id && y === b.id))
                for (const [x, y] of pairs) await api(p('/transitions/'), { method: 'POST', body: { project: Number(projectId), from_status: x, to_status: y } })
              }) : toggle(a.id, b.id))} aria-label={`${a.name} to ${b.name}`} />}</td>)}</tr>)}</tbody></table></div>
          <div className="small muted">Tip: moves that aren't allowed are greyed out while dragging on the board, and rejected by the API.</div>
        </div>
        <div className="card pad col" style={{ marginTop: 16 }}>
          <h3>Import / export issues (CSV)</h3>
          <div className="small muted">Import columns: <span className="mono">title, type, priority, story_points, status, description</span> (title required, max 500 rows / 2 MB).</div>
          <div className="row wrap">
            <Button onClick={() => downloadFile(`/api${p(`/projects/${projectId}/export/`)}`, `${project.data?.key ?? 'project'}-issues.csv`).catch((e) => toast(errMsg(e), true))}>⬇ Export CSV</Button>
            <label className="btn" style={{ cursor: 'pointer' }}>⬆ Import CSV
              <input type="file" accept=".csv,text/csv" hidden onChange={async (e) => {
                const f = e.target.files?.[0]; e.target.value = ''
                if (!f) return
                const form = new FormData(); form.append('file', f)
                try {
                  const r = await api<{ created: number; errors: { row: number }[] }>(p(`/projects/${projectId}/import/`), { method: 'POST', form })
                  toast(`Imported ${r.created} issue${r.created === 1 ? '' : 's'}${r.errors.length ? `, ${r.errors.length} row(s) skipped (rows ${r.errors.slice(0, 5).map((x) => x.row).join(', ')})` : ''}`, r.errors.length > 0)
                  refresh(); qc.invalidateQueries({ queryKey: ['issues'] })
                } catch (x) { toast(errMsg(x), true) }
              }} />
            </label>
          </div>
        </div>
      </div>
    </>
  )
}
