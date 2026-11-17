import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Project } from '../api/types'
import { Avatar, Button, ErrorBox, Field, Meter, Modal, useToast } from '../components/ui'
import { useWs } from '../layout/WorkspaceContext'

export default function Projects() {
  const { projects, slug, can, p } = useWs()
  const [creating, setCreating] = useState(false)
  return (
    <>
      <div className="page-head"><h1>Projects</h1>{can('admin') && <Button variant="primary" onClick={() => setCreating(true)}>+ New project</Button>}</div>
      <div className="grid two">
        {projects.map((x: Project) => (
          <Link key={x.id} to={`/w/${slug}/projects/${x.id}`} className="card pad col" style={{ color: 'inherit', textDecoration: 'none' }}>
            <div className="row spread"><h2>{x.name}</h2><span className="badge accent">{x.key}</span></div>
            <div className="muted">{x.description || 'No description'}</div>
            <Meter used={x.total_issues - x.open_issues} limit={x.total_issues || 1} label="Done" />
            <div className="row spread small muted"><span>{x.open_issues} open · {x.total_issues} total</span><span className="row">Lead <Avatar user={x.lead_detail} size="sm" /></span></div>
          </Link>))}
      </div>
      {creating && <NewProject onClose={() => setCreating(false)} path={p('/projects/')} />}
    </>
  )
}

function NewProject({ onClose, path }: { onClose: () => void; path: string }) {
  const qc = useQueryClient(); const toast = useToast()
  const [key, setKey] = useState(''); const [name, setName] = useState(''); const [description, setDescription] = useState('')
  const m = useMutation({ mutationFn: () => api(path, { method: 'POST', body: { key, name, description } }), onSuccess: () => { qc.invalidateQueries({ queryKey: ['projects'] }); toast('Project created'); onClose() } })
  return (
    <Modal title="New project" onClose={onClose}>
      <form className="col gap-12" onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate() }}>
        {m.isError && !(m.error as any).isPlanLimit && <ErrorBox error={m.error} />}
        <Field label="Name"><input className="input" required autoFocus value={name} onChange={(e) => { setName(e.target.value); if (!key) setKey(e.target.value.replace(/[^A-Za-z]/g, '').slice(0, 4).toUpperCase()) }} /></Field>
        <Field label="Key (used in issue ids, e.g. WEB-12; cannot be changed later)"><input className="input mono" required value={key} maxLength={10} onChange={(e) => setKey(e.target.value.toUpperCase())} /></Field>
        <Field label="Description"><textarea className="textarea" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        <div className="row" style={{ justifyContent: 'flex-end' }}><Button type="button" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={m.isPending}>Create</Button></div>
      </form>
    </Modal>
  )
}
