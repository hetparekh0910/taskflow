import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Avatar, Meter, Modal, PriorityMark, RoleBadge, ToastProvider, formatDate, renderMentions, timeAgo, useToast } from './ui'

const ago = (ms: number) => new Date(Date.now() - ms).toISOString()

describe('timeAgo', () => {
  it.each([[5_000, 'just now'], [5 * 60_000, '5m ago'], [3 * 3_600_000, '3h ago'], [2 * 86_400_000, '2d ago']])('%i ms -> %s', (ms, out) => expect(timeAgo(ago(ms))).toBe(out))
})
describe('formatDate', () => {
  it('formats a date-only string without timezone shifting', () => expect(formatDate('2026-11-20')).toMatch(/Nov\s20|20\sNov/))
  it('shows a dash for empty values', () => { expect(formatDate(null)).toBe('-'); expect(formatDate(undefined)).toBe('-') })
})
describe('renderMentions', () => {
  it('wraps @handles in a highlighted span and leaves the rest as text', () => {
    render(<p>{renderMentions('hi @alice and @bob.smith, ping')}</p>)
    const marks = document.querySelectorAll('.mention')
    expect([...marks].map((m) => m.textContent)).toEqual(['@alice', '@bob.smith'])
    expect(screen.getByText(/ping/)).toBeInTheDocument()
  })
})
describe('Meter', () => {
  it('shows usage against the limit', () => { render(<Meter used={2} limit={3} label="Members" />); expect(screen.getByText('2 / 3')).toBeInTheDocument() })
  it('shows infinity for unlimited plans', () => { render(<Meter used={12} limit={null} label="Projects" />); expect(screen.getByText('12 / ∞')).toBeInTheDocument() })
  it('turns red when the limit is reached and amber when close', () => {
    const { container, rerender } = render(<Meter used={3} limit={3} label="M" />)
    expect(container.querySelector('.bar')).toHaveClass('full')
    rerender(<Meter used={9} limit={10} label="M" />)
    expect(container.querySelector('.bar')).toHaveClass('warn')
  })
})
describe('small components', () => {
  it('Avatar shows initials, or a question mark for unassigned', () => {
    const { rerender } = render(<Avatar user={{ display_name: 'Alice Johnson', avatar_color: '#123456' }} />)
    expect(screen.getByText('AJ')).toBeInTheDocument()
    rerender(<Avatar user={null} />)
    expect(screen.getByText('?')).toBeInTheDocument()
  })
  it('RoleBadge and PriorityMark render their value', () => {
    render(<><RoleBadge role="owner" /><PriorityMark p="highest" /></>)
    expect(screen.getByText('owner')).toHaveClass('accent')
    expect(screen.getByTitle('highest priority')).toHaveClass('prio-highest')
  })
})
describe('Modal', () => {
  it('closes on Escape', async () => {
    const onClose = vi.fn()
    render(<Modal title="Hello" onClose={onClose}><p>body</p></Modal>)
    expect(screen.getByRole('dialog', { name: 'Hello' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
describe('toasts', () => {
  it('shows a message then removes it', () => {
    vi.useFakeTimers()
    function Btn() { const t = useToast(); return <button onClick={() => t('Saved!')}>go</button> }
    render(<ToastProvider><Btn /></ToastProvider>)
    act(() => screen.getByText('go').click())
    expect(screen.getByText('Saved!')).toBeInTheDocument()
    act(() => { vi.advanceTimersByTime(4000) })
    expect(screen.queryByText('Saved!')).not.toBeInTheDocument()
    vi.useRealTimers()
  })
})
