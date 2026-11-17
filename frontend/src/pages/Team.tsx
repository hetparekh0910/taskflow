import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Invitation, Member, Role } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Avatar, Button, ConfirmButton, ErrorBox, Field, Loading, Modal, RoleBadge, errMsg, formatDate, useToast } from '../components/ui'
import { useWs } from '../layout/WorkspaceContext'

const ROLES: Role[] = ['owner', 'admin', 'member', 'viewer']
const DESC: Record<Role, string> = { owner: 'Billing, delete workspace, everything', admin: 'Projects, sprints, workflows, members, audit log', member: 'Create and edit issues, comment, attach files', viewer: 'Read-only access' }

export default function Team() {
  const { p, role, can, slug } = useWs()
  const { user } = useAuth()
  const qc = useQueryClient(); const toast = useToast()
  const [inviting, setInviting] = useState(false)
  const members = useQuery({ queryKey: ['members', p('')], queryFn: () => api<Member[]>(p('/members/')) })
  const invites = useQuery({ queryKey: ['invites', slug], enabled: can('admin'), queryFn: () => api<Invitation[]>(p('/invitations/')) })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['members'] }); qc.invalidateQueries({ queryKey: ['invites'] }); qc.invalidateQueries({ queryKey: ['billing'] }) }
  const setRole = useMutation({ mutationFn: (v: { id: number; role: Role }) => api(p(`/members/${v.id}/`), { method: 'PATCH', body: { role: v.role } }), onSuccess: () => { refresh(); toast('Role updated') }, onError: (e) => toast(errMsg(e), true) })
  const remove = useMutation({ mutationFn: (id: number) => api(p(`/members/${id}/`), { method: 'DELETE' }), onSuccess: refresh, onError: (e) => toast(errMsg(e), true) })
  if (members.isLoading) return <Loading />
  return (
    <>
      <div className="page-head"><div><h1>Team</h1><div className="muted">Your role here: <RoleBadge role={role} /></div></div>{can('admin') && <Button variant="primary" onClick={() => setInviting(true)}>+ Invite</Button>}</div>
      <div className="card" style={{ marginBottom: 16 }}><table className="table"><thead><tr><th>Member</th><th>Role</th><th>Joined</th><th /></tr></thead><tbody>
        {members.data?.map((m) => (
          <tr key={m.id}><td><div className="row"><Avatar user={m.user} size="lg" /><div><strong>{m.user.display_name}</strong>{m.user.id === user?.id && <span className="badge" style={{ marginLeft: 6 }}>you</span>}<div className="small muted">{m.user.email}</div></div></div></td>
            <td>{can('admin') && !(m.role === 'owner' && role !== 'owner') ? (
              <select className="select sm" value={m.role} onChange={(e) => setRole.mutate({ id: m.id, role: e.target.value as Role })} aria-label={`Role of ${m.user.display_name}`}>
                {ROLES.filter((r) => r !== 'owner' || role === 'owner').map((r) => <option key={r}>{r}</option>)}</select>) : <RoleBadge role={m.role} />}</td>
            <td className="muted">{formatDate(m.joined_at)}</td>
            <td style={{ textAlign: 'right' }}>{(can('admin') || m.user.id === user?.id) && <ConfirmButton size="sm" variant="danger" message={m.user.id === user?.id ? 'Leave this workspace?' : `Remove ${m.user.display_name}?`} onConfirm={() => remove.mutate(m.id)}>{m.user.id === user?.id ? 'Leave' : 'Remove'}</ConfirmButton>}</td></tr>))}</tbody></table></div>
      {can('admin') && !!invites.data?.length && (
        <div className="card pad"><h3>Pending invitations</h3><table className="table"><tbody>
          {invites.data.map((i) => <tr key={i.id}><td>{i.email}</td><td><RoleBadge role={i.role} /></td><td className="muted small">invited by {i.invited_by_name}</td>
            <td style={{ textAlign: 'right' }}><Button size="sm" onClick={() => { navigator.clipboard?.writeText(`${location.origin}/signup?invite=${i.token}`); toast('Invite link copied') }}>Copy link</Button>{' '}
              <ConfirmButton size="sm" variant="ghost" message="Revoke invitation?" onConfirm={() => api(p(`/invitations/${i.id}/`), { method: 'DELETE' }).then(refresh)}>Revoke</ConfirmButton></td></tr>)}</tbody></table></div>)}
      <div className="card pad" style={{ marginTop: 16 }}><h3>Role permissions</h3><table className="table"><tbody>{ROLES.map((r) => <tr key={r}><td style={{ width: 110 }}><RoleBadge role={r} /></td><td className="muted">{DESC[r]}</td></tr>)}</tbody></table></div>
      {inviting && <InviteModal path={p('/invitations/')} onClose={() => setInviting(false)} onDone={refresh} />}
    </>
  )
}

function InviteModal({ path, onClose, onDone }: { path: string; onClose: () => void; onDone: () => void }) {
  const [email, setEmail] = useState(''); const [role, setRole] = useState<Role>('member')
  const m = useMutation({ mutationFn: () => api<Invitation>(path, { method: 'POST', body: { email, role } }), onSuccess: onDone })
  return (
    <Modal title="Invite a teammate" onClose={onClose}>
      {m.isSuccess ? (
        <div className="col gap-12"><div className="badge success">Invitation sent to {m.data.email}</div>
          <Field label="Or share this link directly"><input className="input mono" readOnly value={`${location.origin}/signup?invite=${m.data.token}`} onFocus={(e) => e.target.select()} /></Field>
          <div className="row" style={{ justifyContent: 'flex-end' }}><Button variant="primary" onClick={onClose}>Done</Button></div></div>
      ) : (
        <form className="col gap-12" onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate() }}>
          {m.isError && !(m.error as any).isPlanLimit && <ErrorBox error={m.error} />}
          <Field label="Email"><input className="input" type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Role"><select className="select" value={role} onChange={(e) => setRole(e.target.value as Role)}>{ROLES.filter((r) => r !== 'owner').map((r) => <option key={r} value={r}>{r} - {DESC[r]}</option>)}</select></Field>
          <div className="row" style={{ justifyContent: 'flex-end' }}><Button type="button" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={m.isPending}>Send invite</Button></div>
        </form>)}
    </Modal>
  )
}
