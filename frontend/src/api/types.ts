export type Role = 'owner' | 'admin' | 'member' | 'viewer'
export const ROLE_RANK: Record<Role, number> = { viewer: 0, member: 1, admin: 2, owner: 3 }

export interface User { id: number; email: string; full_name: string; display_name: string; avatar_color: string }
export interface Workspace { id: number; name: string; slug: string; plan: 'free' | 'pro' | 'business'; subscription_status: string; role: Role | null }
export interface Member { id: number; user: User; role: Role; joined_at: string }
export interface Invitation { id: number; email: string; role: Role; token: string; created_at: string; invited_by_name: string | null }

export interface Status { id: number; project: number; name: string; category: 'todo' | 'in_progress' | 'done'; order: number; color: string; issue_count?: number }
export interface Transition { id: number; project: number; from_status: number; to_status: number }
export interface Label { id: number; name: string; color: string }
export interface Project {
  id: number; key: string; name: string; description: string; lead: number | null; lead_detail: User | null
  archived: boolean; open_issues: number; total_issues: number; created_at: string
}
export type IssueType = 'task' | 'bug' | 'story' | 'epic'
export type Priority = 'lowest' | 'low' | 'medium' | 'high' | 'highest'
export interface Issue {
  id: number; key: string; number: number; project: number; type: IssueType; title: string; description: string
  status: number; status_detail: Status; priority: Priority
  assignee: number | null; assignee_detail: User | null; reporter: number | null; reporter_detail: User | null
  sprint: number | null; parent: number | null; story_points: number | null
  labels: number[]; label_details: Label[]; due_date: string | null; rank: number; resolved_at: string | null
  created_at: string; updated_at: string; comment_count: number; attachment_count: number
}
export interface BoardColumn { id: number; order: number; wip_limit: number | null; status: Status; allowed_to: number[]; issues: Issue[] }
export interface Board { id: number; project: Project; columns: BoardColumn[]; active_sprint: Sprint | null }
export interface Sprint {
  id: number; project: number; name: string; goal: string; start_date: string | null; end_date: string | null
  state: 'planned' | 'active' | 'closed'; committed_points: number; completed_points: number
  issue_count: number; total_points: number; done_points: number
}
export interface Comment { id: number; issue: number; author: number | null; author_detail: User | null; body: string; created_at: string }
export interface Attachment { id: number; issue: number; name: string; size: number; content_type: string; download_url: string; created_at: string; uploaded_by_detail: User | null }
export interface AuditEntry { id: number; actor_name: string; action: 'create' | 'update' | 'delete'; model: string; object_id: string; object_repr: string; changes: Record<string, { old?: unknown; new?: unknown } | unknown>; created_at: string }
export interface Notification { id: number; kind: string; message: string; issue: number | null; issue_key: string | null; read: boolean; created_at: string }
export interface Webhook { id: number; url: string; events: string[]; active: boolean; description: string; secret: string; created_at: string }
export interface Delivery { id: number; webhook: number; event: string; attempts: number; success: boolean; status_code: number | null; error: string; created_at: string; next_retry_at: string | null; payload: unknown; response_body: string }
export interface PlanSpec { key: string; name: string; price_usd: number; max_members: number | null; max_projects: number | null; max_storage_mb: number | null; webhooks: boolean; audit_log_days: number | null }
export interface Billing { plan: string; subscription_status: string; limits: PlanSpec; usage: { members: number; pending_invites: number; projects: number; storage_mb: number }; plans: PlanSpec[]; mode: 'mock' | 'stripe'; can_manage: boolean }
export interface Dashboard {
  totals: { issues: number; open: number; done: number; overdue: number; created_7d: number; resolved_7d: number }
  by_status: { name: string; count: number; color: string; category: string }[]
  by_priority: { priority: string; count: number }[]
  by_type: { type: string; count: number }[]
  workload: { user_id: number | null; name: string; open: number; points: number }[]
  flow: { date: string; created: number; resolved: number }[]
  velocity: { sprint: string; committed: number; completed: number }[]
}
export interface Burndown { days: { date: string; ideal: number; remaining: number | null }[]; total_points: number }
export interface Paged<T> { count: number; results: T[] }
