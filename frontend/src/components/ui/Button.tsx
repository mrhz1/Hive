import type { VariantProps } from 'class-variance-authority'
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { buttonVariants } from './Button.styles'
import { Spinner } from './Spinner'

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & {
    /** Shows a spinner and blocks interaction while a request is in flight. */
    isLoading?: boolean
    leadingIcon?: ReactNode
  }

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant,
    size,
    fullWidth,
    isLoading = false,
    leadingIcon,
    className,
    children,
    disabled,
    type = 'button',
    ...props
  },
  ref
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || isLoading}
      aria-busy={isLoading}
      className={cn(buttonVariants({ variant, size, fullWidth }), className)}
      {...props}
    >
      {isLoading ? <Spinner size="sm" label="" /> : leadingIcon}
      {children}
    </button>
  )
})
