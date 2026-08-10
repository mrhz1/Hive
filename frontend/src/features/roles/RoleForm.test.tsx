import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { ALL_PERMISSIONS } from '@/schemas/common'

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
  // FormLayout renders a cancel Link.
  Link: ({ children }: { children: ReactNode }) => <a href="#">{children}</a>,
}))
vi.mock('@/hooks/useResources', () => ({
  roleHooks: {
    useCreate: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useUpdate: () => ({ mutateAsync: vi.fn(), isPending: false }),
  },
}))

const { RoleForm } = await import('./RoleForm')

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('RoleForm permission editor', () => {
  it('offers every grant the API recognises', () => {
    render(<RoleForm />, { wrapper })

    for (const permission of ALL_PERMISSIONS) {
      expect(
        screen.getByRole('checkbox', { name: permission }),
        `${permission} is not offered in the editor`
      ).toBeInTheDocument()
    }
  })

  it('offers the files grants under their own action names', () => {
    render(<RoleForm />, { wrapper })

    for (const action of ['read', 'upload', 'download', 'delete']) {
      expect(
        screen.getByRole('checkbox', { name: `files:${action}` })
      ).toBeInTheDocument()
    }
    // The CRUD names must not appear for files.
    expect(screen.queryByRole('checkbox', { name: 'files:view' })).toBeNull()
    expect(screen.queryByRole('checkbox', { name: 'files:create' })).toBeNull()
  })

  it('checks a files grant when clicked', async () => {
    render(<RoleForm />, { wrapper })

    const box = screen.getByRole('checkbox', { name: 'files:download' })
    expect(box).not.toBeChecked()

    await userEvent.click(box)

    expect(screen.getByRole('checkbox', { name: 'files:download' })).toBeChecked()
  })

  it('the row toggle selects that resource only', async () => {
    render(<RoleForm />, { wrapper })

    await userEvent.click(screen.getByRole('button', { name: 'files' }))

    for (const action of ['read', 'upload', 'download', 'delete']) {
      expect(screen.getByRole('checkbox', { name: `files:${action}` })).toBeChecked()
    }
    expect(screen.getByRole('checkbox', { name: 'user:view' })).not.toBeChecked()
  })
})
