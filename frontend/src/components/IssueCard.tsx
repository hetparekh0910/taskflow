import type { Issue } from '../api/types'
import { Avatar, PriorityMark, TypeIcon } from './ui'

export function IssueCardBody({ issue, onOpen }: { issue: Issue; onOpen?: () => void }) {
  const overdue = !!issue.due_date && issue.status_detail.category !== 'done' && new Date(issue.due_date + 'T23:59:59') < new Date()
  return (
    <>
      <div className="issue-title" onClick={onOpen} style={{ cursor: 'pointer' }}>{issue.title}</div>
      {issue.label_details.length > 0 && (
        <div className="row wrap" style={{ gap: 4 }}>{issue.label_details.map((l) => <span key={l.id} className="label-chip" style={{ background: l.color }}>{l.name}</span>)}</div>
      )}
      <div className="issue-meta">
        <TypeIcon type={issue.type} />
        <span className="mono" onClick={onOpen} style={{ cursor: 'pointer' }}>{issue.key}</span>
        <PriorityMark p={issue.priority} />
        {issue.due_date && <span className={`due ${overdue ? 'overdue' : ''}`} title="Due date">📅 {new Date(issue.due_date + 'T00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>}
        {issue.comment_count > 0 && <span title="Comments">💬 {issue.comment_count}</span>}
        {issue.attachment_count > 0 && <span title="Attachments">📎 {issue.attachment_count}</span>}
        <span className="grow" />
        {issue.story_points != null && <span className="points" title="Story points">{issue.story_points}</span>}
        <Avatar user={issue.assignee_detail} size="sm" />
      </div>
    </>
  )
}
