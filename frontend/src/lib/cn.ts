import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Merges class names and resolves Tailwind conflicts, so a caller's
 * `className` reliably overrides a component's defaults instead of the
 * winner depending on stylesheet order.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
