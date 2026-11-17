import { arrayMove } from '@dnd-kit/sortable'
import type { BoardColumn, Issue } from '../api/types'

export type MovePlan =
  | { kind: 'noop' }
  | { kind: 'error'; message: string }
  | { kind: 'move'; activeId: number; src: BoardColumn; dst: BoardColumn; list: Issue[]; above: number | null; below: number | null }

const idOf = (s: string) => Number(s.split(':')[1])

/**
 * Pure decision logic for a Kanban drop. Given the columns, the dragged card id and what it was
 * dropped on ("issue:12" or "col:3"), work out the new order and the neighbours to send to the API.
 * `droppedBelowMiddle` says whether the card landed in the lower half of the card it was dropped on
 * (only matters when moving to a different column).
 */
export function planMove(cols: BoardColumn[], activeId: number, overKey: string, droppedBelowMiddle = false): MovePlan {
  const src = cols.find((c) => c.issues.some((i) => i.id === activeId))
  if (!src) return { kind: 'noop' }
  const overIsColumn = overKey.startsWith('col:')
  const overId = idOf(overKey)
  const dst = overIsColumn ? cols.find((c) => c.status.id === overId) : cols.find((c) => c.issues.some((i) => i.id === overId))
  if (!dst) return { kind: 'noop' }
  const sameColumn = dst.status.id === src.status.id

  if (!sameColumn && !src.allowed_to.includes(dst.status.id)) {
    return { kind: 'error', message: `Workflow does not allow moving from "${src.status.name}" to "${dst.status.name}".` }
  }
  const issue = src.issues.find((i) => i.id === activeId)!
  let list: Issue[]
  if (overIsColumn) {
    // dropped on the empty area of a column => goes to the bottom
    list = sameColumn ? [...src.issues.filter((i) => i.id !== activeId), issue] : [...dst.issues, issue]
  } else {
    if (overId === activeId) return { kind: 'noop' }
    if (sameColumn) {
      list = arrayMove(src.issues, src.issues.findIndex((i) => i.id === activeId), src.issues.findIndex((i) => i.id === overId))
    } else {
      const overIdx = dst.issues.findIndex((i) => i.id === overId)
      list = [...dst.issues]
      list.splice(overIdx + (droppedBelowMiddle ? 1 : 0), 0, issue)
    }
  }
  if (sameColumn && src.issues.map((i) => i.id).join() === list.map((i) => i.id).join()) return { kind: 'noop' }
  if (!sameColumn && dst.wip_limit != null && dst.issues.length >= dst.wip_limit) {
    return { kind: 'error', message: `WIP limit of ${dst.wip_limit} reached for "${dst.status.name}".` }
  }
  const idx = list.findIndex((i) => i.id === activeId)
  return { kind: 'move', activeId, src, dst, list, above: list[idx - 1]?.id ?? null, below: list[idx + 1]?.id ?? null }
}

/** Optimistic board state after a planned move. */
export function applyMove(cols: BoardColumn[], plan: Extract<MovePlan, { kind: 'move' }>): BoardColumn[] {
  const { activeId, src, dst, list } = plan
  return cols.map((c) => {
    if (c.status.id === dst.status.id) {
      return { ...c, issues: list.map((i) => (i.id === activeId ? { ...i, status: dst.status.id, status_detail: dst.status } : i)) }
    }
    if (c.status.id === src.status.id) return { ...c, issues: c.issues.filter((i) => i.id !== activeId) }
    return c
  })
}
