import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Delivery, Paged, Webhook } from '../api/types'
import { Button, ConfirmButton, Empty, ErrorBox, Field, Loading, Modal, errMsg, timeAgo, useToast } from '../components/ui'
import { useWs } from '../layout/WorkspaceContext'

export default function Webhooks() {
  const { p, can, slug, ws } = useWs()
  const qc = useQueryClient(); const toast = useToast()
  const [creating, setCreating] = useState(false)
  const [viewing, setViewing] = useState<Webhook | null>(null)
  const hooks = useQuery({ queryKey: ['webhooks', slug], enabled: can('admin'), queryFn: () => api<Webhook[]>(p('/webhooks/')) })
  const refresh = () => qc.invalidateQueries({ queryKey: ['webhooks'] })
  const test = useMutation({ mutationFn: (id: number) => api<Delivery>(p(`/webhooks/${id}/test/`), { method: 'POST' }),
    onSuccess: (d) => { toast(d.success ? `Ping delivered (HTTP ${d.status_code})` : `Ping failed: ${d.error}`, !d.success); qc.invalidateQueries({ queryKey: ['deliveries'] }) } })
  if (!can('admin')) return <div className="empty">Only admins can manage webhooks.</div>
  if (hooks.isLoading) return <Loading />
  return (
    <>
      <div className="page-head"><div><h1>Webhooks</h1><div className="muted">Send signed HTTP events to your own systems. Retries use exponential backoff.</div></div>
        <Button variant="primary" onClick={() => setCreating(true)}>+ Add webhook</Button></div>
      {ws.plan === 'free' && <div className="card pad" style={{ marginBottom: 16, background: 'var(--warn-soft)' }}>Webhooks are a Pro feature. <a href={`/w/${slug}/billing`}>Upgrade</a> to create one.</div>}
      {!hooks.data?.length ? <Empty title="No webhooks yet">Subscribe a URL to events like <span className="mono">issue.created</span>.</Empty> : (
        <div className="col gap-12">{hooks.data.map((h) => (
          <div key={h.id} className="card pad col">
            <div className="row spread wrap"><div><strong className="mono">{h.url}</strong> <span className={`badge ${h.active ? 'success' : ''}`}>{h.active ? 'active' : 'paused'}</span>
              {h.description && <div className="small muted">{h.description}</div>}</div>
              <div className="row"><Button size="sm" onClick={() => test.mutate(h.id)} disabled={test.isPending}>Send test</Button>
                <Button size="sm" onClick={() => setViewing(h)}>Deliveries</Button>
                <Button size="sm" onClick={() => api(p(`/webhooks/${h.id}/`), { method: 'PATCH', body: { active: !h.active } }).then(refresh)}>{h.active ? 'Pause' : 'Resume'}</Button>
                <ConfirmButton size="sm" variant="danger" message="Delete webhook?" onConfirm={() => api(p(`/webhooks/${h.id}/`), { method: 'DELETE' }).then(refresh)}>Delete</ConfirmButton></div></div>
            <div className="row wrap" style={{ gap: 4 }}>{h.events.map((e) => <span key={e} className="badge">{e}</span>)}</div>
            <details className="small"><summary className="muted" style={{ cursor: 'pointer' }}>Signing secret &amp; verification</summary>
              <div className="mono" style={{ margin: '6px 0' }}>{h.secret}</div>
              <div className="muted">Each request has <span className="mono">X-TaskFlow-Timestamp</span> and <span className="mono">X-TaskFlow-Signature: sha256=HMAC_SHA256(secret, timestamp + "." + body)</span>. Recompute and compare in constant time; reject old timestamps.</div></details>
          </div>))}</div>)}
      {creating && <CreateHook path={p('/webhooks/')} eventsPath={p('/webhooks/events/')} onClose={() => setCreating(false)} onDone={refresh} />}
      {viewing && <Deliveries hook={viewing} onClose={() => setViewing(null)} />}
    </>
  )
}

function CreateHook({ path, eventsPath, onClose, onDone }: { path: string; eventsPath: string; onClose: () => void; onDone: () => void }) {
  const events = useQuery({ queryKey: ['webhook-events'], queryFn: () => api<string[]>(eventsPath) })
  const [url, setUrl] = useState(''); const [description, setDescription] = useState(''); const [sel, setSel] = useState<string[]>(['*'])
  const m = useMutation({ mutationFn: () => api(path, { method: 'POST', body: { url, description, events: sel } }), onSuccess: () => { onDone(); onClose() } })
  const toggle = (e: string) => setSel((s) => (e === '*' ? ['*'] : s.includes(e) ? s.filter((x) => x !== e) : [...s.filter((x) => x !== '*'), e]))
  return (
    <Modal title="Add webhook" onClose={onClose}>
      <form className="col gap-12" onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate() }}>
        {m.isError && !(m.error as any).isPlanLimit && <ErrorBox error={m.error} />}
        <Field label="Payload URL"><input className="input mono" type="url" required autoFocus placeholder="https://example.com/hook" value={url} onChange={(e) => setUrl(e.target.value)} /></Field>
        <Field label="Description"><input className="input" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        <Field label="Events" group><div className="row wrap" style={{ gap: 6 }}>
          {['*', ...(events.data ?? [])].map((e) => <label key={e} className="badge" style={{ cursor: 'pointer', ...(sel.includes(e) ? { background: 'var(--accent-soft)', color: 'var(--accent)' } : {}) }}>
            <input type="checkbox" hidden checked={sel.includes(e)} onChange={() => toggle(e)} />{e === '*' ? 'all events' : e}</label>)}</div></Field>
        <div className="row" style={{ justifyContent: 'flex-end' }}><Button type="button" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={m.isPending || !sel.length}>Create</Button></div>
      </form>
    </Modal>
  )
}

function Deliveries({ hook, onClose }: { hook: Webhook; onClose: () => void }) {
  const { p } = useWs(); const qc = useQueryClient(); const toast = useToast()
  const q = useQuery({ queryKey: ['deliveries', hook.id], refetchInterval: 5000, queryFn: () => api<Paged<Delivery>>(p('/webhook-deliveries/'), { params: { webhook: hook.id } }) })
  const [open, setOpen] = useState<number | null>(null)
  const redeliver = useMutation({ mutationFn: (id: number) => api<Delivery>(p(`/webhook-deliveries/${id}/redeliver/`), { method: 'POST' }),
    onSuccess: (d) => { qc.invalidateQueries({ queryKey: ['deliveries'] }); toast(d.success ? 'Delivered' : `Failed: ${d.error}`, !d.success) }, onError: (e) => toast(errMsg(e), true) })
  return (
    <Modal title={`Deliveries · ${hook.url}`} onClose={onClose} wide>
      {q.isLoading ? <Loading /> : !q.data?.results.length ? <div className="muted">No deliveries yet. Create or move an issue.</div> : (
        <table className="table"><thead><tr><th>Event</th><th>Result</th><th>Attempts</th><th>When</th><th /></tr></thead><tbody>
          {q.data.results.map((d) => <><tr key={d.id}><td className="mono">{d.event}</td>
            <td><span className={`badge ${d.success ? 'success' : 'danger'}`}>{d.success ? `HTTP ${d.status_code}` : d.error || 'failed'}</span>{!d.success && d.next_retry_at && <span className="small muted"> · retry {timeAgo(d.next_retry_at).replace(' ago', '')}</span>}</td>
            <td>{d.attempts}</td><td className="small muted">{timeAgo(d.created_at)}</td>
            <td style={{ textAlign: 'right' }}><Button size="sm" variant="ghost" onClick={() => setOpen(open === d.id ? null : d.id)}>Payload</Button><Button size="sm" onClick={() => redeliver.mutate(d.id)}>Redeliver</Button></td></tr>
            {open === d.id && <tr key={`${d.id}p`}><td colSpan={5}><pre className="mono small" style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{JSON.stringify(d.payload, null, 2)}</pre></td></tr>}</>)}</tbody></table>)}
    </Modal>
  )
}
