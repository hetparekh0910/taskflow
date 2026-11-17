import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Billing as B, PlanSpec } from '../api/types'
import { Button, ConfirmButton, ErrorBox, Loading, Meter, errMsg, useToast } from '../components/ui'
import { useWs } from '../layout/WorkspaceContext'

const lim = (n: number | null, unit = '') => (n === null ? 'Unlimited' : `${n.toLocaleString()}${unit}`)
const storage = (mb: number | null) => (mb === null ? 'Unlimited' : mb >= 1024 ? `${mb / 1024} GB` : `${mb} MB`)

export default function Billing() {
  const { p, slug, can } = useWs()
  const qc = useQueryClient(); const toast = useToast(); const [sp, setSp] = useSearchParams()
  const q = useQuery({ queryKey: ['billing', slug], queryFn: () => api<B>(p('/billing/')) })
  useEffect(() => {
    const c = sp.get('checkout')
    if (c === 'success') {
      // Don't wait for Stripe's webhook: ask the server to pull the subscription from Stripe right now.
      setSp({}, { replace: true })
      api<{ plan: string }>(p('/billing/sync/'), { method: 'POST' })
        .then((r) => toast(r.plan === 'free' ? 'Payment received. Your plan will update in a moment.' : `You're now on the ${r.plan} plan. Thank you!`))
        .catch(() => toast('Payment received. Your plan will update in a moment.'))
        .finally(() => qc.invalidateQueries())
    } else if (c) { toast('Checkout cancelled', true); setSp({}, { replace: true }) }
  }, [])
  const refresh = () => { qc.invalidateQueries({ queryKey: ['billing'] }); qc.invalidateQueries({ queryKey: ['ws'] }); qc.invalidateQueries({ queryKey: ['workspaces'] }) }
  const checkout = useMutation({ mutationFn: (plan: string) => api<{ url: string }>(p('/billing/checkout/'), { method: 'POST', body: { plan } }), onSuccess: (r) => { window.location.href = r.url }, onError: (e) => toast(errMsg(e), true) })
  const portal = useMutation({ mutationFn: () => api<{ url: string }>(p('/billing/portal/'), { method: 'POST' }), onSuccess: (r) => { window.location.href = r.url }, onError: (e) => toast(errMsg(e), true) })
  const cancel = useMutation({ mutationFn: () => api(p('/billing/cancel/'), { method: 'POST' }), onSuccess: () => { toast('Subscription cancelled'); refresh() }, onError: (e) => toast(errMsg(e), true) })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorBox error={q.error} />
  const b = q.data
  const order = ['free', 'pro', 'business']
  const feats = (s: PlanSpec) => [`${lim(s.max_members)} members`, `${lim(s.max_projects)} projects`, `${storage(s.max_storage_mb)} file storage`, s.webhooks ? 'Webhooks & API events' : 'No webhooks', `Audit log${s.audit_log_days ? `: ${s.audit_log_days} days` : ': unlimited retention'}`]
  return (
    <>
      <div className="page-head"><div><h1>Billing &amp; plan</h1><div className="muted">Current plan: <strong style={{ textTransform: 'capitalize' }}>{b.plan}</strong> {b.subscription_status && <span className={`badge ${b.subscription_status === 'active' ? 'success' : 'warn'}`}>{b.subscription_status.replace('_', ' ')}</span>}</div></div>
        {b.mode === 'mock' && <span className="badge warn" title="No Stripe keys configured; checkout is simulated">Test mode: simulated payments</span>}</div>
      <div className="card pad col gap-12" style={{ marginBottom: 16 }}><h3>Usage vs plan limits</h3>
        <Meter label="Members (incl. pending invites)" used={b.usage.members + b.usage.pending_invites} limit={b.limits.max_members} />
        <Meter label="Projects" used={b.usage.projects} limit={b.limits.max_projects} />
        <Meter label="Storage" used={b.usage.storage_mb} limit={b.limits.max_storage_mb} unit=" MB" /></div>
      <div className="plans">
        {b.plans.sort((a, c) => order.indexOf(a.key) - order.indexOf(c.key)).map((s) => {
          const current = s.key === b.plan; const up = order.indexOf(s.key) > order.indexOf(b.plan)
          return (
            <div key={s.key} className={`card plan ${current ? 'current' : ''}`}>
              <div className="row spread"><h2>{s.name}</h2>{current && <span className="badge accent">Current</span>}</div>
              <div className="price">${s.price_usd}<span className="small muted"> /month</span></div>
              <ul>{feats(s).map((f) => <li key={f}>{f}</li>)}</ul>
              <div style={{ marginTop: 'auto' }}>
                {current ? <Button disabled style={{ width: '100%' }}>Your plan</Button>
                  : up ? <Button variant="primary" style={{ width: '100%' }} disabled={!b.can_manage || checkout.isPending} title={!b.can_manage ? 'Only the owner can change the plan' : ''} onClick={() => checkout.mutate(s.key)}>Upgrade to {s.name}</Button>
                    : s.key === 'free' && b.plan !== 'free' ? <ConfirmButton style={{ width: '100%' }} disabled={!b.can_manage} message="Cancel your subscription and return to Free? Limits apply immediately for new items." onConfirm={() => cancel.mutate()}>Downgrade to Free</ConfirmButton>
                      : <Button disabled style={{ width: '100%' }}>Contact owner</Button>}
              </div></div>)})}
      </div>
      {b.can_manage && b.mode === 'stripe' && b.plan !== 'free' && <div style={{ marginTop: 16 }}><Button onClick={() => portal.mutate()}>Manage payment method &amp; invoices</Button></div>}
      {!can('owner') && <div className="small muted" style={{ marginTop: 12 }}>Only the workspace owner can change the plan.</div>}
    </>
  )
}

/** Stand-in for Stripe Checkout, used only when no Stripe keys are configured. */
export function MockCheckout() {
  const [sp] = useSearchParams(); const nav = useNavigate(); const { p, slug } = useWs(); const qc = useQueryClient(); const toast = useToast()
  const plan = sp.get('plan') ?? 'pro'
  const [busy, setBusy] = useState(false)
  async function pay() {
    setBusy(true)
    try { await api(p('/billing/mock/confirm/'), { method: 'POST', body: { plan } }); qc.invalidateQueries(); toast(`Upgraded to ${plan}`); nav(`/w/${slug}/billing`) }
    catch (e) { toast(errMsg(e), true) } finally { setBusy(false) }
  }
  return (
    <div className="center"><div className="card pad col gap-12" style={{ width: 400 }}>
      <span className="badge warn" style={{ alignSelf: 'flex-start' }}>Simulated checkout (test mode)</span>
      <h2>Subscribe to {plan[0].toUpperCase() + plan.slice(1)}</h2>
      <div className="muted">This mimics Stripe Checkout. With real test keys set on the server, you'd be redirected to Stripe instead. Use card <span className="mono">4242 4242 4242 4242</span> there.</div>
      <input className="input mono" defaultValue="4242 4242 4242 4242" readOnly aria-label="Card number" />
      <div className="row"><input className="input mono" defaultValue="12 / 34" readOnly /><input className="input mono" defaultValue="123" readOnly /></div>
      <Button variant="primary" disabled={busy} onClick={pay}>{busy ? 'Processing…' : 'Pay now'}</Button>
      <Button variant="ghost" onClick={() => nav(`/w/${slug}/billing`)}>Cancel</Button>
    </div></div>
  )
}
