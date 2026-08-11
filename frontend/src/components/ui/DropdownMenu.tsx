import { MoreHorizontal } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
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

/** Gap between the trigger and the menu, and from the viewport edge. */
const OFFSET = 4
const MARGIN = 8

/** Below this, dropping downwards is not worth it -- flip instead. */
const MIN_DROP_SPACE = 180

/**
 * Where the menu goes, in viewport coordinates.
 *
 * Anchored to the trigger's rect rather than positioned by the normal
 * flow, because the menu is portalled to <body>: a table cell cannot
 * clip it and a sticky cell's stacking context cannot bury it.
 */
function placementFor(rect: DOMRect, align: 'left' | 'right'): CSSProperties {
  const spaceBelow = window.innerHeight - rect.bottom - OFFSET - MARGIN
  const spaceAbove = rect.top - OFFSET - MARGIN

  // Prefer downwards, but flip when the row is near the bottom of the
  // window -- which is exactly where the last rows of a table are.
  const dropUp = spaceBelow < MIN_DROP_SPACE && spaceAbove > spaceBelow

  const horizontal: CSSProperties =
    align === 'right'
      ? { right: Math.max(MARGIN, window.innerWidth - rect.right) }
      : { left: Math.max(MARGIN, rect.left) }

  return {
    position: 'fixed',
    ...horizontal,
    ...(dropUp
      ? { bottom: window.innerHeight - rect.top + OFFSET, maxHeight: spaceAbove }
      : { top: rect.bottom + OFFSET, maxHeight: spaceBelow }),
  }
}

/**
 * A row's actions behind one button.
 *
 * The file table had six buttons per row, which is wider than the file
 * name it belongs to and turns a scan of the table into a scan of the
 * buttons. Everything still one click away, just not all at once.
 *
 * The menu renders in a portal. Inside the table it was clipped by the
 * wrapper's `overflow-x-auto` (a non-visible overflow on one axis clips
 * the other as well) and painted under the refetch overlay, because the
 * sticky actions cell it sat in creates its own stacking context. Neither
 * can reach it out here.
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
  const [style, setStyle] = useState<CSSProperties | null>(null)
  const [activeIndex, setActiveIndex] = useState(-1)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuId = useId()

  const usable = actions.filter((action) => !action.disabled)

  const close = useCallback(() => {
    setIsOpen(false)
    setActiveIndex(-1)
  }, [])

  const reposition = useCallback(() => {
    const trigger = triggerRef.current
    if (trigger) setStyle(placementFor(trigger.getBoundingClientRect(), align))
  }, [align])

  function toggle() {
    if (isOpen) {
      close()
      return
    }
    reposition()
    setIsOpen(true)
  }

  useEffect(() => {
    if (!isOpen) return

    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node
      // The menu is portalled, so it is not inside the trigger's parent.
      if (triggerRef.current?.contains(target)) return
      if (menuRef.current?.contains(target)) return
      close()
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        close()
        triggerRef.current?.focus()
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

    // Fixed coordinates go stale the moment anything scrolls. Capture,
    // so a scroll inside the table body counts too.
    const onScroll = () => reposition()

    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
    }
  }, [isOpen, usable.length, close, reposition])

  function select(action: MenuAction) {
    if (action.disabled) return
    close()
    action.onSelect()
  }

  const menu =
    isOpen && style ? (
      <div
        ref={menuRef}
        id={menuId}
        role="menu"
        aria-label={label}
        style={style}
        className="z-[100] min-w-52 overflow-y-auto overscroll-contain rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] py-1 shadow-lg"
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
                  {action.isLoading ? <Spinner size="sm" label="" /> : action.icon}
                </span>
                <span className="truncate">{action.label}</span>
              </button>
            </div>
          )
        })}
      </div>
    ) : null

  return (
    <>
      <Button
        ref={triggerRef}
        size="sm"
        variant="outline"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-controls={isOpen ? menuId : undefined}
        aria-label={label}
        isLoading={isBusy}
        onClick={toggle}
      >
        {!isBusy ? <MoreHorizontal className="size-4" aria-hidden="true" /> : null}
        <span className="sr-only">{label}</span>
      </Button>

      {menu ? createPortal(menu, document.body) : null}
    </>
  )
}
