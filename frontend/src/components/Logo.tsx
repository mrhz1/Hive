import { cn } from '@/lib/cn'

const LOGO_FILE = 'logo.svg'

export const LOGO_URL = `${import.meta.env.BASE_URL}${LOGO_FILE}`

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
