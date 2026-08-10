import { Link } from '@tanstack/react-router'
import type { FormEvent, ReactNode } from 'react'
import { Button } from './ui/Button'

export function FormLayout({
  mode,
  entityLabel,
  cancelTo,
  isSubmitting,
  onSubmit,
  children,
  footerNote,
  submitLabel: submitLabelOverride,
}: {
  mode: 'create' | 'edit'
  entityLabel: string
  cancelTo: string
  isSubmitting: boolean
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  children: ReactNode
  footerNote?: ReactNode
  submitLabel?: string
}) {
  const submitLabel =
    submitLabelOverride ??
    (mode === 'create' ? `Create ${entityLabel}` : 'Save changes')

  return (
    <form
      onSubmit={onSubmit}
      noValidate
      className="space-y-6 rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-6 shadow-sm"
    >
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">{children}</div>

      <div className="flex flex-col-reverse items-stretch gap-3 border-t border-[rgb(var(--border))] pt-6 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-[rgb(var(--foreground-muted))]">{footerNote}</p>
        <div className="flex flex-col-reverse gap-3 sm:flex-row">
          <Link to={cancelTo}>
            <Button variant="outline" fullWidth disabled={isSubmitting}>
              Cancel
            </Button>
          </Link>
          <Button type="submit" isLoading={isSubmitting}>
            {isSubmitting ? 'Saving…' : submitLabel}
          </Button>
        </div>
      </div>
    </form>
  )
}

/** Makes a field span the full width of the two-column form grid. */
export function FullWidth({ children }: { children: ReactNode }) {
  return <div className="sm:col-span-2">{children}</div>
}
