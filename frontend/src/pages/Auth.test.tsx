import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { tokens } from '../api/client'
import { Login, Signup } from './Auth'

const res = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const ME = { id: 1, email: 'alice@acme.test', full_name: 'Alice', display_name: 'Alice', avatar_color: '#000' }

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/" element={<div>HOME PAGE</div>} />
          <Route path="/w/:slug" element={<div>WORKSPACE PAGE</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('Login page', () => {
  it('fills the form when a demo account button is clicked', async () => {
    renderAt('/login')
    await userEvent.click(screen.getByRole('button', { name: /Alice \(Owner, Acme\)/ }))
    expect(screen.getByLabelText('Email')).toHaveValue('alice@acme.test')
    expect(screen.getByLabelText('Password')).toHaveValue('demo12345')
  })
  it('shows a friendly message on wrong credentials', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res(401, { detail: 'No active account found with the given credentials' })))
    renderAt('/login')
    await userEvent.type(screen.getByLabelText('Email'), 'x@y.com')
    await userEvent.type(screen.getByLabelText('Password'), 'wrongpass')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong email or password.')
    expect(tokens.access).toBeNull()
  })
  it('stores tokens and navigates home on success', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(res(200, { access: 'A', refresh: 'R' }))
      .mockResolvedValueOnce(res(200, ME)))
    renderAt('/login')
    await userEvent.type(screen.getByLabelText('Email'), 'alice@acme.test')
    await userEvent.type(screen.getByLabelText('Password'), 'demo12345')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(screen.getByText('HOME PAGE')).toBeInTheDocument())
    expect(tokens.access).toBe('A')
    expect(tokens.refresh).toBe('R')
  })
})

describe('Signup page', () => {
  it('creates a workspace and lands in it', async () => {
    const f = vi.fn().mockResolvedValue(res(201, { access: 'A', refresh: 'R', user: ME, workspace: { slug: 'foo-inc' } }))
    vi.stubGlobal('fetch', f)
    renderAt('/signup')
    await userEvent.type(screen.getByLabelText('Your name'), 'Alice')
    await userEvent.type(screen.getByLabelText('Work email'), 'a@foo.com')
    await userEvent.type(screen.getByLabelText('Password (8+ characters)'), 'longenough1')
    await userEvent.type(screen.getByLabelText('Company / workspace name'), 'Foo Inc')
    await userEvent.click(screen.getByRole('button', { name: 'Create workspace' }))
    await waitFor(() => expect(screen.getByText('WORKSPACE PAGE')).toBeInTheDocument())
    expect(JSON.parse(f.mock.calls[0][1].body)).toMatchObject({ email: 'a@foo.com', workspace_name: 'Foo Inc' })
  })
  it('shows server validation errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res(400, { email: ['An account with this email already exists.'] })))
    renderAt('/signup')
    await userEvent.type(screen.getByLabelText('Your name'), 'A')
    await userEvent.type(screen.getByLabelText('Work email'), 'a@foo.com')
    await userEvent.type(screen.getByLabelText('Password (8+ characters)'), 'longenough1')
    await userEvent.type(screen.getByLabelText('Company / workspace name'), 'Foo')
    await userEvent.click(screen.getByRole('button', { name: 'Create workspace' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already exists')
  })
})
