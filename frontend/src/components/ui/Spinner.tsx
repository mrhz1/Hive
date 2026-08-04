import { cn } from '@/lib/cn'

const SIZES = {
  sm: 'size-4 border-2',
  md: 'size-6 border-2',
  lg: 'size-8 border-[3px]',
} as const

export function Spinner({
  className,
  label = 'Loading',
  size = 'md',
}: {
  className?: string
  /** Announced to screen readers; pass '' when a parent already labels it. */
  label?: string
  size?: keyof typeof SIZES
}) {
  return (
    <span
      role="status"
      aria-live="polite"
      className={cn('inline-flex items-center gap-2', className)}
    >
      <span
        aria-hidden="true"
        className={cn(
          'animate-spin rounded-full border-current border-t-transparent opacity-70',
          SIZES[size]
        )}
      />
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  )
}

/** Full-area loading state for page bodies and cards. */
export function LoadingBlock({
  label = 'Loading',
  className,
}: {
  label?: string
  className?: string
}) {
  return (
    <div
      className={cn('flex flex-col items-center justify-center gap-3 py-14', className)}
    >
      <Spinner size="lg" label="" />
      <p className="text-sm text-[rgb(var(--foreground-muted))]">{label}</p>
    </div>
  )
}
