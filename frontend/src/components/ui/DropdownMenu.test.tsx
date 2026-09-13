import { render, screen, waitFor } from '@testing-library/react'
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

  function positionTrigger(top: number) {
    window.innerHeight = 800
    window.innerWidth = 1200
    Element.prototype.getBoundingClientRect = vi.fn(function (this: Element) {
      if ((this as HTMLElement).tagName !== 'BUTTON') return new DOMRect()
      return new DOMRect(1000, top, 40, 32)
    }) as unknown as () => DOMRect
  }

  it('renders outside the table, so nothing can clip or cover it', async () => {
    const user = userEvent.setup()
    positionTrigger(100)

    const { container } = render(
      <div style={{ overflowX: 'auto' }} data-testid="table-wrapper">
        <div style={{ position: 'sticky', zIndex: 10 }}>
          <DropdownMenu actions={actions()} />
        </div>
      </div>
    )

    await user.click(screen.getByRole('button', { name: 'Actions' }))

    const menu = screen.getByRole('menu')
    expect(menu).toBeInTheDocument()

    expect(container.contains(menu)).toBe(false)
    expect(menu.style.position).toBe('fixed')
  })

  it('drops downwards when there is room below', async () => {
    const user = userEvent.setup()
    positionTrigger(100)

    render(<DropdownMenu actions={actions()} />)
    await user.click(screen.getByRole('button', { name: 'Actions' }))

    const menu = screen.getByRole('menu')
    expect(menu.style.top).toBe('136px')
    expect(menu.style.bottom).toBe('')
  })

  it('flips upwards on the last rows, instead of running off the screen', async () => {
    const user = userEvent.setup()
    positionTrigger(740)

    render(<DropdownMenu actions={actions()} />)
    await user.click(screen.getByRole('button', { name: 'Actions' }))

    const menu = screen.getByRole('menu')
    expect(menu.style.bottom).toBe('64px')
    expect(menu.style.top).toBe('')
  })

  it('flips as soon as the space below gets tight, not only at the edge', async () => {
    const user = userEvent.setup()

    positionTrigger(600)

    render(<DropdownMenu actions={actions()} />)
    await user.click(screen.getByRole('button', { name: 'Actions' }))

    expect(screen.getByRole('menu').style.bottom).toBe('204px')
  })

  it('never grows past the space it has', async () => {
    const user = userEvent.setup()
    positionTrigger(100)

    render(<DropdownMenu actions={actions()} />)
    await user.click(screen.getByRole('button', { name: 'Actions' }))

    expect(screen.getByRole('menu').style.maxHeight).toBe('656px')
  })

  it('follows the trigger when the page scrolls', async () => {
    const user = userEvent.setup()
    positionTrigger(300)

    render(<DropdownMenu actions={actions()} />)
    await user.click(screen.getByRole('button', { name: 'Actions' }))
    expect(screen.getByRole('menu').style.top).toBe('336px')

    positionTrigger(200)
    window.dispatchEvent(new Event('scroll'))

    await waitFor(() =>
      expect(screen.getByRole('menu').style.top).toBe('236px')
    )
  })

  it('closes when a click lands outside the portalled menu', async () => {
    const user = userEvent.setup()
    positionTrigger(100)

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

  it('stays open when a click lands inside the portalled menu', async () => {
    const user = userEvent.setup()
    positionTrigger(100)

    render(<DropdownMenu actions={actions()} />)
    await user.click(screen.getByRole('button', { name: 'Actions' }))

    await user.click(screen.getByRole('menu'))

    expect(screen.getByRole('menu')).toBeInTheDocument()
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
