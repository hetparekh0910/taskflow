import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import type { Dashboard as D } from '../api/types'
import { ErrorBox, Loading } from '../components/ui'
import { useWs } from '../layout/WorkspaceContext'

const PRIO_COLOR: Record<string, string> = { highest: '#dc2626', high: '#f97316', medium: '#eab308', low: '#60a5fa', lowest: '#94a3b8' }

export default function Dashboard() {
  const { p, projects, ws } = useWs()
  const [project, setProject] = useState('')
  const { data, isLoading, error } = useQuery({ queryKey: ['dashboard', ws.slug, project], queryFn: () => api<D>(p('/dashboard/'), { params: { project } }) })
  if (isLoading) return <Loading />
  if (error || !data) return <ErrorBox error={error} />
  const t = data.totals
  const stat = (v: number | string, l: string, tone = '') => <div className="card pad stat"><div className="v" style={tone ? { color: tone } : undefined}>{v}</div><div className="l">{l}</div></div>
  return (
    <>
      <div className="page-head">
        <div><h1>Dashboard</h1><div className="muted">{ws.name} · live overview</div></div>
        <select className="select sm" value={project} onChange={(e) => setProject(e.target.value)} aria-label="Project filter">
          <option value="">All projects</option>{projects.map((x) => <option key={x.id} value={x.id}>{x.key} · {x.name}</option>)}
        </select>
      </div>
      <div className="grid stats" style={{ marginBottom: 16 }}>
        {stat(t.open, 'Open issues')}{stat(t.done, 'Done')}{stat(t.overdue, 'Overdue', t.overdue ? 'var(--danger)' : undefined)}
        {stat(t.created_7d, 'Created (7d)')}{stat(t.resolved_7d, 'Resolved (7d)', 'var(--success)')}
      </div>
      <div className="grid two">
        <div className="card pad"><h3>Issues by status</h3>
          <ResponsiveContainer width="100%" height={240}><BarChart data={data.by_status}><CartesianGrid strokeDasharray="3 3" stroke="var(--border)" /><XAxis dataKey="name" tick={{ fontSize: 12, fill: 'var(--text-2)' }} /><YAxis allowDecimals={false} tick={{ fill: 'var(--text-2)' }} /><Tooltip />
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>{data.by_status.map((s) => <Cell key={s.name} fill={s.color} />)}</Bar></BarChart></ResponsiveContainer></div>
        <div className="card pad"><h3>By priority</h3>
          <ResponsiveContainer width="100%" height={240}><PieChart><Pie isAnimationActive={false} data={data.by_priority} dataKey="count" nameKey="priority" innerRadius={50} outerRadius={85} paddingAngle={2}>
            {data.by_priority.map((x) => <Cell key={x.priority} fill={PRIO_COLOR[x.priority]} />)}</Pie><Tooltip /><Legend /></PieChart></ResponsiveContainer></div>
        <div className="card pad"><h3>Created vs resolved (14 days)</h3>
          <ResponsiveContainer width="100%" height={240}><LineChart data={data.flow.map((f) => ({ ...f, d: f.date.slice(5) }))}><CartesianGrid strokeDasharray="3 3" stroke="var(--border)" /><XAxis dataKey="d" tick={{ fontSize: 11, fill: 'var(--text-2)' }} /><YAxis allowDecimals={false} tick={{ fill: 'var(--text-2)' }} /><Tooltip /><Legend />
            <Line type="linear" dataKey="created" stroke="#6366f1" strokeWidth={2} dot={false} /><Line type="linear" dataKey="resolved" stroke="#22c55e" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></div>
        <div className="card pad"><h3>Sprint velocity</h3>
          {data.velocity.length ? <ResponsiveContainer width="100%" height={240}><BarChart data={data.velocity}><CartesianGrid strokeDasharray="3 3" stroke="var(--border)" /><XAxis dataKey="sprint" tick={{ fill: 'var(--text-2)' }} /><YAxis tick={{ fill: 'var(--text-2)' }} /><Tooltip /><Legend />
            <Bar dataKey="committed" fill="#94a3b8" radius={[4, 4, 0, 0]} /><Bar dataKey="completed" fill="#6366f1" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer>
            : <div className="empty small">Close a sprint to see velocity.</div>}</div>
        <div className="card pad" style={{ gridColumn: '1 / -1' }}><h3>Team workload (open issues)</h3>
          <table className="table"><thead><tr><th>Person</th><th>Open</th><th>Story points</th><th style={{ width: '40%' }} /></tr></thead><tbody>
            {data.workload.map((w) => <tr key={w.user_id ?? 'none'}><td>{w.user_id ? w.name : <span className="muted">Unassigned</span>}</td><td>{w.open}</td><td>{w.points}</td>
              <td><div className="bar"><i style={{ width: `${Math.min(100, (w.open / Math.max(...data.workload.map((x) => x.open), 1)) * 100)}%` }} /></div></td></tr>)}
            {!data.workload.length && <tr><td colSpan={4} className="muted">Nothing open. 🎉</td></tr>}</tbody></table></div>
      </div>
    </>
  )
}
