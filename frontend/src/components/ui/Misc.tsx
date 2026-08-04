import { cva, type VariantProps } from 'class-variance-authority'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

/** Surface panel used for forms, detail views and dashboard cards. */
export function Card({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] shadow-sm',
        className
      )}
    >
      {children}
    </div>
  )
}

/** Page title, supporting text and right-aligned actions. */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-[rgb(var(--foreground))]">
          {title}
        </h1>
        {description ? (
          <p className="mt-1 text-sm text-[rgb(var(--foreground-muted))]">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 gap-2">{actions}</div> : null}
    </div>
  )
}

const badgeVariants = cva(
  'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
  {
    variants: {
      tone: {
        neutral:
          'border border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] text-[rgb(var(--foreground-muted))]',
        success:
          'bg-[rgb(var(--success-rgb))]/15 text-[rgb(var(--success-foreground))] dark:text-[rgb(var(--success))]',
        danger:
          'bg-[rgb(var(--danger-rgb))]/15 text-[rgb(var(--danger-foreground))] dark:text-[rgb(var(--danger))]',
        warning:
          'bg-[rgb(var(--warning-rgb))]/15 text-[rgb(var(--warning-foreground))] dark:text-[rgb(var(--warning))]',
        info: 'bg-teal-500/15 text-teal-700 dark:text-teal-300',
      },
    },
    defaultVariants: { tone: 'neutral' },
  }
)

export function Badge({
  children,
  tone,
  className,
}: VariantProps<typeof badgeVariants> & {
  children: ReactNode
  className?: string
}) {
  return <span className={cn(badgeVariants({ tone }), className)}>{children}</span>
}

/** Read-only key/value row, used by detail pages. */
export function DescriptionItem({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-1 border-b border-[rgb(var(--border))] py-3 last:border-b-0 sm:flex-row sm:gap-4">
      <dt className="w-full text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase sm:w-56 sm:shrink-0">
        {label}
      </dt>
      <dd className="min-w-0 text-sm break-words">{children}</dd>
    </div>
  )
}
