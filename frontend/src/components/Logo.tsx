import { APP_LOGO } from '@/lib/brand'
import { cn } from '@/lib/cn'

export const LOGO_URL = `${import.meta.env.BASE_URL}${APP_LOGO}`

export function Logo({ className, label }: { className?: string; label?: string }) {
  return (
    <img
      src={LOGO_URL}
      alt={label ?? ''}
      aria-hidden={label ? undefined : true}
      className={cn('size-8 shrink-0 object-contain', className)}
      draggable={false}
    />
  )
}
