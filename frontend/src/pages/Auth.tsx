import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button, ErrorBox, Field } from '../components/ui'

function Hero() {
  return (
    <div className="hero">
      <div className="brand" style={{ color: '#fff', fontSize: 20 }}><span className="logo" style={{ background: '#fff', color: '#4f46e5' }}>T</span> TaskFlow</div>
      <h1>Plan, track and ship work, one isolated workspace per company.</h1>
      <ul>
        <li>Drag-and-drop Kanban boards with custom workflows</li>
        <li>Sprints, backlog and burndown charts</li>
        <li>Role-based access, audit log and webhooks</li>
        <li>Subscription plans with enforced limits</li>
      </ul>
    </div>
  )
}

export function Login() {
  const { login } = useAuth()
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null)
    try { await login(email, password); nav('/') } catch (x: any) {
      setErr(x?.status === 401 ? new Error('Wrong email or password.') : x)
    } finally { setBusy(false) }
  }
  const demo = (e: string) => { setEmail(e); setPassword('demo12345') }
  return (
    <div className="auth">
      <Hero />
      <div className="form">
        <form className="card col gap-12" onSubmit={submit}>
          <h1>Welcome back</h1>
          {!!err && <ErrorBox error={err} />}
          <Field label="Email"><input className="input" type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Password"><input className="input" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          <Button variant="primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</Button>
          <div className="small muted">No account? <Link to="/signup">Create a workspace</Link></div>
          <div className="card pad small col" style={{ background: 'var(--surface-2)', boxShadow: 'none' }}>
            <strong>Demo accounts</strong>
            <div className="row wrap">
              <button type="button" className="btn sm" onClick={() => demo('alice@acme.test')}>Alice (Owner, Acme)</button>
              <button type="button" className="btn sm" onClick={() => demo('carol@acme.test')}>Carol (Member)</button>
              <button type="button" className="btn sm" onClick={() => demo('erin@acme.test')}>Erin (Viewer)</button>
              <button type="button" className="btn sm" onClick={() => demo('gina@globex.test')}>Gina (Owner, Globex)</button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}

export function Signup() {
  const { register } = useAuth()
  const nav = useNavigate()
  const [params] = useSearchParams()
  const invite = params.get('invite') ?? ''
  const [f, setF] = useState({ full_name: '', email: '', password: '', workspace_name: '' })
  const [inviteInfo, setInviteInfo] = useState<{ email: string; workspace_name: string; role: string } | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!invite) return
    api<{ email: string; workspace_name: string; role: string }>(`/invitations/${invite}/`, { auth: false })
      .then((i) => { setInviteInfo(i); setF((x) => ({ ...x, email: i.email })) })
      .catch(setErr)
  }, [invite])

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null)
    try {
      const slug = await register({ ...f, ...(invite ? { invite_token: invite, workspace_name: undefined } : {}) })
      nav(slug ? `/w/${slug}` : '/')
    } catch (x) { setErr(x) } finally { setBusy(false) }
  }
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value })
  return (
    <div className="auth">
      <Hero />
      <div className="form">
        <form className="card col gap-12" onSubmit={submit}>
          <h1>{inviteInfo ? `Join ${inviteInfo.workspace_name}` : 'Create your workspace'}</h1>
          {inviteInfo && <div className="badge accent">You were invited as {inviteInfo.role}</div>}
          {!!err && <ErrorBox error={err} />}
          <Field label="Your name"><input className="input" required value={f.full_name} onChange={set('full_name')} /></Field>
          <Field label="Work email"><input className="input" type="email" required readOnly={!!inviteInfo} value={f.email} onChange={set('email')} /></Field>
          <Field label="Password (8+ characters)"><input className="input" type="password" required minLength={8} value={f.password} onChange={set('password')} /></Field>
          {!invite && <Field label="Company / workspace name"><input className="input" required value={f.workspace_name} onChange={set('workspace_name')} placeholder="Acme Inc." /></Field>}
          <Button variant="primary" disabled={busy}>{busy ? 'Creating…' : invite ? 'Accept invitation' : 'Create workspace'}</Button>
          <div className="small muted">Already have an account? <Link to="/login">Sign in</Link></div>
        </form>
      </div>
    </div>
  )
}
