import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DropdownMenu, type MenuAction } from './DropdownMenu'

function actions(overrides: Partial<MenuAction>[] = []): MenuAction[] {
  const base: MenuAction[] = [
    { id: 'open', label: 'View original', onSelect: vi.fn() },
    { id: 'deid', label: 'De-identify', onSelect: vi.fn() },
    { id: 'delete', label: 'Delete file', tone: 'danger', onSelect: vi.fn() },
  ]
  return base.map((action, index) => ({ ...action, ...overrides[index] }))
}

describe('DropdownMenu', () => {
  it('keeps the actions out of the way until asked', () => {
    render(<DropdownMenu actions={actions()} />)

    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(screen.queryByText('De-identify')).not.toBeInTheDocument()
  })

  it('opens on click and lists every action', async () => {
    const user = userEvent.setup()
    render(<DropdownMenu actions={actions()} />)

    await user.click(screen.getByRole('button', { name: 'Actions' }))

    expect(screen.getByRole('menu')).toBeInTheDocument()
    expect(screen.getAllByRole('menuitem')).toHaveLength(3)
  })

  it('runs the action that was chosen, and closes', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<DropdownMenu actions={actions([{}, { onSelect }])} />)

    await user.click(screen.getByRole('button', { name: 'Actions' }))
    await user.click(screen.getByRole('menuitem', { name: /De-identify/ }))

    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('does not run a disabled action', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(
      <DropdownMenu
        actions={actions([{}, { onSelect, disabled: true, title: 'Not yet' }])}
      />
    )

    await user.click(screen.getByRole('button', { name: 'Actions' }))
    await user.click(screen.getByRole('menuitem', { name: /De-identify/ }))

    expect(onSelect).not.toHaveBeenCalled()
    // Still open: nothing happened, so nothing should have closed.
    expect(screen.getByRole('menu')).toBeInTheDocument()
  })

  it('says why an action is unavailable rather than just greying it out', async () => {
    const user = userEvent.setup()
    render(
      <DropdownMenu
        actions={actions([
          {},
          { disabled: true, title: 'Only PDF, DICOM and Word files' },
        ])}
      />
    )

    await user.click(screen.getByRole('button', { name: 'Actions' }))

    expect(screen.getByRole('menuitem', { name: /De-identify/ })).toHaveAttribute(
      'title',
      'Only PDF, DICOM and Word files'
    )
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    render(<DropdownMenu actions={actions()} />)

    await user.click(screen.getByRole('button', { name: 'Actions' }))
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes when a click lands outside it', async () => {
    const user = userEvent.setup()
    render(
      <div>
        <DropdownMenu actions={actions()} />
        <button type="button">elsewhere</button>
      </div>
    )

    await user.click(screen.getByRole('button', { name: 'Actions' }))
    await user.click(screen.getByRole('button', { name: 'elsewhere' }))

    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('is labelled for the row it belongs to', async () => {
    const user = userEvent.setup()
    render(<DropdownMenu actions={actions()} label="Actions for scan.pdf" />)

    const trigger = screen.getByRole('button', { name: 'Actions for scan.pdf' })
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')

    await user.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })
})
