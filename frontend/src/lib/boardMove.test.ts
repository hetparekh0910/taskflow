import { describe, expect, it } from 'vitest'
import { board } from '../test/fixtures'
import { applyMove, planMove } from './boardMove'

const ids = (cols: ReturnType<typeof board>, col: number) => cols[col].issues.map((i) => i.id)

describe('planMove: reordering inside a column', () => {
  it('moves a card down between two neighbours', () => {
    const p = planMove(board(), 1, 'issue:3')
    expect(p.kind).toBe('move')
    if (p.kind !== 'move') return
    expect(p.list.map((i) => i.id)).toEqual([2, 3, 1])
    expect(p.above).toBe(3)
    expect(p.below).toBeNull()
  })
  it('moves a card up to the top', () => {
    const p = planMove(board(), 3, 'issue:1')
    if (p.kind !== 'move') throw new Error('expected move')
    expect(p.list.map((i) => i.id)).toEqual([3, 1, 2])
    expect(p.above).toBeNull()
    expect(p.below).toBe(1)
  })
  it('is a no-op when dropped on itself or in the same position', () => {
    expect(planMove(board(), 2, 'issue:2').kind).toBe('noop')
    expect(planMove(board(), 1, 'issue:2').kind).toBe('move') // 1 over 2 swaps them
    expect(planMove(board(), 3, 'col:10').kind).toBe('noop')  // already at the bottom of its own column
  })
})

describe('planMove: moving across columns', () => {
  it('drops onto an empty column', () => {
    const p = planMove(board(), 1, 'col:30')
    if (p.kind !== 'move') throw new Error('expected move')
    expect(p.dst.status.name).toBe('Done')
    expect(p.above).toBeNull()
    expect(p.below).toBeNull()
  })
  it('drops onto the bottom of a populated column when dropped on the column area', () => {
    const p = planMove(board(), 1, 'col:20')
    if (p.kind !== 'move') throw new Error('expected move')
    expect(p.list.map((i) => i.id)).toEqual([4, 1])
    expect(p.above).toBe(4)
    expect(p.below).toBeNull()
  })
  it('inserts before or after the card it landed on depending on the pointer half', () => {
    const before = planMove(board(), 1, 'issue:4', false)
    const after = planMove(board(), 1, 'issue:4', true)
    if (before.kind !== 'move' || after.kind !== 'move') throw new Error('expected moves')
    expect(before.list.map((i) => i.id)).toEqual([1, 4])
    expect(before.below).toBe(4)
    expect(after.list.map((i) => i.id)).toEqual([4, 1])
    expect(after.above).toBe(4)
  })
  it('ignores unknown cards and unknown targets', () => {
    expect(planMove(board(), 999, 'col:20').kind).toBe('noop')
    expect(planMove(board(), 1, 'col:999').kind).toBe('noop')
    expect(planMove(board(), 1, 'issue:999').kind).toBe('noop')
  })
})

describe('planMove: workflow and WIP rules', () => {
  it('blocks transitions the workflow does not allow, with a readable message', () => {
    const cols = board({ allowed: { 10: [20], 20: [10, 30], 30: [20] } })
    const p = planMove(cols, 1, 'col:30')
    expect(p).toEqual({ kind: 'error', message: 'Workflow does not allow moving from "To Do" to "Done".' })
    expect(planMove(cols, 1, 'col:20').kind).toBe('move')
  })
  it('blocks moving into a column that is at its WIP limit, but allows reordering inside it', () => {
    const cols = board({ wip: { 20: 1 } })
    expect(planMove(cols, 1, 'col:20')).toEqual({ kind: 'error', message: 'WIP limit of 1 reached for "In Progress".' })
    const reorder = board({ wip: { 10: 3 } })
    expect(planMove(reorder, 1, 'issue:3').kind).toBe('move')
  })
})

describe('applyMove (optimistic UI)', () => {
  it('moves the card between columns and updates its status', () => {
    const cols = board()
    const p = planMove(cols, 2, 'col:30')
    if (p.kind !== 'move') throw new Error('expected move')
    const next = applyMove(cols, p)
    expect(ids(next, 0)).toEqual([1, 3])
    expect(ids(next, 2)).toEqual([2])
    expect(next[2].issues[0].status).toBe(30)
    expect(next[2].issues[0].status_detail.name).toBe('Done')
  })
  it('does not mutate the previous state', () => {
    const cols = board()
    const p = planMove(cols, 2, 'col:30')
    if (p.kind !== 'move') throw new Error('expected move')
    applyMove(cols, p)
    expect(ids(cols, 0)).toEqual([1, 2, 3])
  })
  it('reorders in place for a same-column move', () => {
    const cols = board()
    const p = planMove(cols, 1, 'issue:3')
    if (p.kind !== 'move') throw new Error('expected move')
    expect(ids(applyMove(cols, p), 0)).toEqual([2, 3, 1])
  })
})
