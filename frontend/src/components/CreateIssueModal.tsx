import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Issue, IssueType, Member, Priority, Project, Sprint } from '../api/types'
import { useWs } from '../layout/WorkspaceContext'
import { Button, ErrorBox, Field, Modal, useToast } from './ui'

export default function CreateIssueModal({ projectId, sprintId, statusId, onClose, onCreated }: {
  projectId?: number; sprintId?: number | null; statusId?: number; onClose: () => void; onCreated?: (i: Issue) => void
}) {
  const { p, projects } = useWs()
  const qc = useQueryClient()
  const toast = useToast()
  const [project, setProject] = useState<number>(projectId ?? projects[0]?.id)
  const [title, setTitle] = useState('')
  const [type, setType] = useState<IssueType>('task')
  const [priority, setPriority] = useState<Priority>('medium')
  const [points, setPoints] = useState('')
  const [assignee, setAssignee] = useState('')
  const [description, setDescription] = useState('')
  const members = useQuery({ queryKey: ['members', p('')], queryFn: () => api<Member[]>(p('/members/')) })
  const sprints = useQuery({ queryKey: ['sprints', project], enabled: !!project, queryFn: () => api<{ results: Sprint[] }>(p('/sprints/'), { params: { project } }) })
  const [sprint, setSprint] = useState<string>(sprintId ? String(sprintId) : '')

  const m = useMutation({
    mutationFn: () => api<Issue>(p('/issues/'), { method: 'POST', body: {
      project, title, type, priority, description,
      story_points: points ? Number(points) : null, assignee: assignee ? Number(assignee) : null,
      sprint: sprint ? Number(sprint) : null, ...(statusId ? { status: statusId } : {}),
    } }),
    onSuccess: (i) => {
      qc.invalidateQueries({ queryKey: ['board'] }); qc.invalidateQueries({ queryKey: ['issues'] }); qc.invalidateQueries({ queryKey: ['sprints'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] }); qc.invalidateQueries({ queryKey: ['projects'] })
      toast(`Created ${i.key}`); onCreated?.(i); onClose()
    },
  })
  const open = (sprints.data?.results ?? []).filter((s) => s.state !== 'closed')
  return (
    <Modal title="Create issue" onClose={onClose} wide>
      <form className="col gap-12" onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate() }}>
        {m.isError && !(m.error as any)?.isPlanLimit && <ErrorBox error={m.error} />}
        <div className="row">
          <Field label="Project"><select className="select" value={project} onChange={(e) => setProject(Number(e.target.value))}>
            {projects.filter((x: Project) => !x.archived).map((x: Project) => <option key={x.id} value={x.id}>{x.key} · {x.name}</option>)}</select></Field>
          <Field label="Type"><select className="select" value={type} onChange={(e) => setType(e.target.value as IssueType)}>
            {['task', 'bug', 'story', 'epic'].map((t) => <option key={t}>{t}</option>)}</select></Field>
        </div>
        <Field label="Title"><input className="input" autoFocus required maxLength={255} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="What needs to be done?" /></Field>
        <Field label="Description"><textarea className="textarea" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        <div className="row wrap">
          <Field label="Priority"><select className="select" value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
            {['highest', 'high', 'medium', 'low', 'lowest'].map((t) => <option key={t}>{t}</option>)}</select></Field>
          <Field label="Assignee"><select className="select" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
            <option value="">Unassigned</option>{members.data?.map((m) => <option key={m.user.id} value={m.user.id}>{m.user.display_name}</option>)}</select></Field>
          <Field label="Story points"><input className="input" type="number" min={0} max={100} value={points} onChange={(e) => setPoints(e.target.value)} style={{ width: 90 }} /></Field>
          <Field label="Sprint"><select className="select" value={sprint} onChange={(e) => setSprint(e.target.value)}>
            <option value="">Backlog</option>{open.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
        </div>
        <div className="row spread"><span className="small faint">Tip: press <kbd>c</kbd> anywhere to create an issue</span>
          <div className="row"><Button type="button" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={m.isPending || !title.trim()}>Create</Button></div></div>
      </form>
    </Modal>
  )
}
