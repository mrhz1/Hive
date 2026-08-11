import { MoreHorizontal } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { cn } from '@/lib/cn'
import { Button } from './Button'
import { Spinner } from './Spinner'

export type MenuAction = {
  id: string
  label: string
  icon?: ReactNode
  onSelect: () => void
  disabled?: boolean
  /** Shown instead of the label's normal styling for destructive items. */
  tone?: 'default' | 'danger'
  isLoading?: boolean
  /** Explains a disabled item, which is otherwise a dead end. */
  title?: string
  /** Starts a new group, separated by a rule. */
  separatorBefore?: boolean
}

/**
 * A row's actions behind one button.
 *
 * The file table had six buttons per row, which is wider than the file
 * name it belongs to and turns a scan of the table into a scan of the
 * buttons. Everything still one click away, just not all at once.
 *
 * Closes on outside click, Escape and selection; arrow keys move through
 * the items, because a menu that can only be used with a mouse is not
 * one the keyboard-only half of a clinical workstation can use.
 */
export function DropdownMenu({
  actions,
  label = 'Actions',
  align = 'right',
  isBusy = false,
}: {
  actions: MenuAction[]
  label?: string
  align?: 'left' | 'right'
  isBusy?: boolean
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const containerRef = useRef<HTMLDivElement>(null)
  const menuId = useId()

  const usable = actions.filter((action) => !action.disabled)

  // Closing resets the keyboard cursor, so reopening starts from the top
  // rather than wherever the arrow keys were left. Done here rather than
  // in an effect on isOpen: it belongs to the act of closing.
  const close = useCallback(() => {
    setIsOpen(false)
    setActiveIndex(-1)
  }, [])

  useEffect(() => {
    if (!isOpen) return

    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) close()
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        close()
        return
      }
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return

      event.preventDefault()
      setActiveIndex((current) => {
        if (usable.length === 0) return -1
        const step = event.key === 'ArrowDown' ? 1 : -1
        const next = current + step
        if (next < 0) return usable.length - 1
        if (next >= usable.length) return 0
        return next
      })
    }

    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [isOpen, usable.length, close])

  function select(action: MenuAction) {
    if (action.disabled) return
    close()
    action.onSelect()
  }

  return (
    <div ref={containerRef} className="relative">
      <Button
        size="sm"
        variant="outline"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-controls={isOpen ? menuId : undefined}
        aria-label={label}
        isLoading={isBusy}
        onClick={() => setIsOpen((open) => !open)}
      >
        {!isBusy ? (
          <MoreHorizontal className="size-4" aria-hidden="true" />
        ) : null}
        <span className="sr-only">{label}</span>
      </Button>

      {isOpen ? (
        <div
          id={menuId}
          role="menu"
          aria-label={label}
          className={cn(
            'absolute z-30 mt-1 min-w-52 overflow-hidden rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] py-1 shadow-lg',
            align === 'right' ? 'right-0' : 'left-0'
          )}
        >
          {actions.map((action) => {
            const activeId = usable[activeIndex]?.id
            return (
              <div key={action.id}>
                {action.separatorBefore ? (
                  <div
                    role="separator"
                    className="my-1 border-t border-[rgb(var(--border))]"
                  />
                ) : null}
                <button
                  type="button"
                  role="menuitem"
                  disabled={action.disabled}
                  title={action.title}
                  onMouseEnter={() =>
                    setActiveIndex(usable.findIndex((u) => u.id === action.id))
                  }
                  onClick={() => select(action)}
                  className={cn(
                    'flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors',
                    action.disabled
                      ? 'cursor-not-allowed opacity-40'
                      : 'cursor-pointer',
                    !action.disabled && action.id === activeId
                      ? 'bg-[rgb(var(--background-secondary))]'
                      : '',
                    action.tone === 'danger'
                      ? 'text-rose-600 dark:text-rose-400'
                      : 'text-[rgb(var(--foreground))]'
                  )}
                >
                  <span className="flex size-4 shrink-0 items-center justify-center">
                    {action.isLoading ? (
                      <Spinner size="sm" label="" />
                    ) : (
                      action.icon
                    )}
                  </span>
                  <span className="truncate">{action.label}</span>
                </button>
              </div>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
