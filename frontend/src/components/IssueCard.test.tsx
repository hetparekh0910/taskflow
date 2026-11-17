import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { issue, status, user } from '../test/fixtures'
import { IssueCardBody } from './IssueCard'

const todo = status(1, 'To Do')
const done = status(2, 'Done', 'done')

describe('IssueCardBody', () => {
  it('shows title, key, points, assignee, labels and counters', () => {
    render(<IssueCardBody issue={issue(12, todo, {
      title: 'Fix login', story_points: 5, assignee_detail: user(1, 'Bob Martinez'), type: 'bug',
      label_details: [{ id: 1, name: 'frontend', color: '#3b82f6' }], comment_count: 3, attachment_count: 2,
    })} />)
    expect(screen.getByText('Fix login')).toBeInTheDocument()
    expect(screen.getByText('WEB-12')).toBeInTheDocument()
    expect(screen.getByTitle('Story points')).toHaveTextContent('5')
    expect(screen.getByTitle('Bob Martinez')).toHaveTextContent('BM')
    expect(screen.getByText('frontend')).toBeInTheDocument()
    expect(screen.getByTitle('Comments')).toHaveTextContent('3')
    expect(screen.getByTitle('Attachments')).toHaveTextContent('2')
  })
  it('hides optional parts when empty', () => {
    render(<IssueCardBody issue={issue(1, todo)} />)
    expect(screen.queryByTitle('Story points')).not.toBeInTheDocument()
    expect(screen.queryByTitle('Comments')).not.toBeInTheDocument()
    expect(screen.queryByTitle('Due date')).not.toBeInTheDocument()
  })
  it('flags overdue dates unless the issue is done', () => {
    const { rerender } = render(<IssueCardBody issue={issue(1, todo, { due_date: '2020-01-01' })} />)
    expect(screen.getByTitle('Due date')).toHaveClass('overdue')
    rerender(<IssueCardBody issue={issue(1, done, { due_date: '2020-01-01' })} />)
    expect(screen.getByTitle('Due date')).not.toHaveClass('overdue')
  })
  it('calls onOpen when the title or key is clicked', async () => {
    const onOpen = vi.fn()
    render(<IssueCardBody issue={issue(7, todo, { title: 'Open me' })} onOpen={onOpen} />)
    await userEvent.click(screen.getByText('Open me'))
    await userEvent.click(screen.getByText('WEB-7'))
    expect(onOpen).toHaveBeenCalledTimes(2)
  })
})
