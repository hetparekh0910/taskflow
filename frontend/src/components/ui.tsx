import { createContext, useCallback, useContext, useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import type { IssueType, Priority, User } from '../api/types'
import { ApiError } from '../api/client'

/* ---------- toasts ---------- */
interface Toast { id: number; msg: string; err?: boolean }
const ToastCtx = createContext<(msg: string, err?: boolean) => void>(() => {})
export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const push = useCallback((msg: string, err?: boolean) => {
    const id = Date.now() + Math.random()
    setItems((t) => [...t, { id, msg, err }])
    setTimeout(() => setItems((t) => t.filter((x) => x.id !== id)), err ? 6000 : 3200)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast ${t.err ? 'err' : ''}`}>{t.msg}</div>)}
      </div>
    </ToastCtx.Provider>
  )
}

export function errMsg(e: unknown): string {
  return e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Something went wrong'
}

/* ---------- primitives ---------- */
export function Button({ variant, size, className = '', ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'danger' | 'ghost'; size?: 'sm' | 'icon' }) {
  return <button {...p} className={`btn ${variant ?? ''} ${size ?? ''} ${className}`} />
}

export function Spinner() { return <div className="spinner" role="progressbar" aria-label="Loading" /> }
export function Loading() { return <div className="center"><Spinner /></div> }
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><h3 style={{ color: 'var(--text)' }}>{title}</h3><div style={{ marginTop: 6 }}>{children}</div></div>
}
export function ErrorBox({ error }: { error: unknown }) { return <div className="error" role="alert">{errMsg(error)}</div> }

/** Wraps the control in a <label> so the text is its accessible name (and clicking it focuses the control).
 *  Use `group` when the field holds several controls (chips, checkboxes) so a click can't hit the first one. */
export function Field({ label, children, group }: { label: string; children: ReactNode; group?: boolean }) {
  if (group) return <div className="field" role="group" aria-label={label}><span className="lbl">{label}</span>{children}</div>
  return <label className="field"><span className="lbl">{label}</span>{children}</label>
}

export function Avatar({ user, size }: { user: Pick<User, 'display_name' | 'avatar_color'> | null | undefined; size?: 'sm' | 'lg' }) {
  if (!user) return <span className={`avatar ${size ?? ''}`} style={{ background: 'var(--border-strong)' }} title="Unassigned">?</span>
  const initials = user.display_name.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()
  return <span className={`avatar ${size ?? ''}`} style={{ background: user.avatar_color }} title={user.display_name}>{initials}</span>
}

const TYPE_CH: Record<IssueType, string> = { task: '✓', bug: '!', story: '★', epic: '⚡' }
export function TypeIcon({ type }: { type: IssueType }) { return <span className={`type-icon type-${type}`} title={type}>{TYPE_CH[type]}</span> }
const PRIO_CH: Record<Priority, string> = { highest: '⏫', high: '↑', medium: '=', low: '↓', lowest: '⏬' }
export function PriorityMark({ p }: { p: Priority }) { return <span className={`prio prio-${p}`} title={`${p} priority`}>{PRIO_CH[p]}</span> }

export function RoleBadge({ role }: { role: string | null }) {
  const cls = role === 'owner' ? 'accent' : role === 'admin' ? 'warn' : ''
  return <span className={`badge ${cls}`}>{role}</span>
}

/* ---------- modal / drawer ---------- */
function useEscape(onClose: () => void) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose])
}

export function Modal({ title, onClose, children, wide }: { title?: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEscape(onClose)
  return (
    <div className="overlay-bg" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        {title && <h2>{title}</h2>}
        {children}
      </div>
    </div>
  )
}

export function Drawer({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  useEscape(onClose)
  return (
    <div className="drawer-bg" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <aside className="drawer" role="dialog" aria-modal="true">{children}</aside>
    </div>
  )
}

export function ConfirmButton({ children, onConfirm, message = 'Are you sure?', ...rest }: { onConfirm: () => void; message?: string } & ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'danger' | 'ghost'; size?: 'sm' | 'icon' }) {
  return <Button {...rest} onClick={() => { if (window.confirm(message)) onConfirm() }}>{children}</Button>
}

/* ---------- popover menu ---------- */
export function Menu({ trigger, children, align = 'left' }: { trigger: (open: boolean, toggle: () => void) => ReactNode; children: (close: () => void) => ReactNode; align?: 'left' | 'right' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      {trigger(open, () => setOpen((o) => !o))}
      {open && <div className="menu" style={{ [align]: 0, top: '100%', marginTop: 4 }}>{children(() => setOpen(false))}</div>}
    </div>
  )
}

/* ---------- misc helpers ---------- */
export function timeAgo(iso: string): string {
  const s = Math.max(1, Math.floor((Date.now() - new Date(iso).getTime()) / 1000))
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24); if (d < 30) return `${d}d ago`
  return new Date(iso).toLocaleDateString()
}

export function formatDate(iso: string | null | undefined) {
  return iso ? new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '-'
}

export function Meter({ used, limit, label, unit = '' }: { used: number; limit: number | null; label: string; unit?: string }) {
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0
  const cls = limit && used >= limit ? 'full' : pct > 80 ? 'warn' : ''
  return (
    <div className="col" style={{ gap: 4 }}>
      <div className="row spread small"><span className="muted">{label}</span><span>{used}{unit} / {limit ?? '∞'}{limit ? unit : ''}</span></div>
      <div className={`bar ${cls}`}><i style={{ width: `${limit ? pct : 4}%` }} /></div>
    </div>
  )
}

export function renderMentions(text: string): ReactNode[] {
  return text.split(/(@[A-Za-z0-9._+-]+)/g).map((part, i) => (part.startsWith('@') ? <span key={i} className="mention">{part}</span> : part))
}
