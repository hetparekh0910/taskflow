import { describe, expect, it } from 'vitest'
import { makeCan } from '../layout/WorkspaceContext'
import { ROLE_RANK } from './types'

describe('role hierarchy', () => {
  it('orders viewer < member < admin < owner', () => {
    expect(ROLE_RANK.viewer).toBeLessThan(ROLE_RANK.member)
    expect(ROLE_RANK.member).toBeLessThan(ROLE_RANK.admin)
    expect(ROLE_RANK.admin).toBeLessThan(ROLE_RANK.owner)
  })
  it('makeCan grants a role everything at or below its level', () => {
    const member = makeCan('member')
    expect([member('viewer'), member('member'), member('admin'), member('owner')]).toEqual([true, true, false, false])
    const owner = makeCan('owner')
    expect(['viewer', 'member', 'admin', 'owner'].every((r) => owner(r as never))).toBe(true)
    expect(makeCan('viewer')('member')).toBe(false)
  })
})
