import type { BoardColumn, Issue, Status, User } from '../api/types'

export const user = (id = 1, name = 'Alice Johnson'): User => ({ id, email: `u${id}@x.test`, full_name: name, display_name: name, avatar_color: '#6366f1' })

export const status = (id: number, name: string, category: Status['category'] = 'todo'): Status =>
  ({ id, project: 1, name, category, order: id, color: '#94a3b8' })

export function issue(id: number, st: Status, over: Partial<Issue> = {}): Issue {
  return {
    id, key: `WEB-${id}`, number: id, project: 1, type: 'task', title: `Issue ${id}`, description: '', status: st.id, status_detail: st,
    priority: 'medium', assignee: null, assignee_detail: null, reporter: null, reporter_detail: null, sprint: null, parent: null,
    story_points: null, labels: [], label_details: [], due_date: null, rank: id * 1000, resolved_at: null,
    created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z', comment_count: 0, attachment_count: 0, ...over,
  }
}

/** Three-column board: To Do (1,2,3) / In Progress (4) / Done (empty). Default workflow is open. */
export function board(opts: { allowed?: Record<number, number[]>; wip?: Record<number, number | null> } = {}): BoardColumn[] {
  const todo = status(10, 'To Do'), prog = status(20, 'In Progress', 'in_progress'), done = status(30, 'Done', 'done')
  const all = [10, 20, 30]
  const allowed = opts.allowed ?? { 10: [20, 30], 20: [10, 30], 30: [10, 20] }
  const mk = (id: number, st: Status, issues: Issue[]): BoardColumn =>
    ({ id, order: id, wip_limit: opts.wip?.[st.id] ?? null, status: st, allowed_to: allowed[st.id] ?? all.filter((x) => x !== st.id), issues })
  return [
    mk(1, todo, [issue(1, todo), issue(2, todo), issue(3, todo)]),
    mk(2, prog, [issue(4, prog)]),
    mk(3, done, []),
  ]
}
