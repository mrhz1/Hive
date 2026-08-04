import { Link } from '@tanstack/react-router'
import { OctagonAlert, SearchX, ShieldX } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { Button } from './ui/Button'

const TONES = {
  danger: {
    ring: 'bg-rose-500/10 text-rose-600 dark:text-rose-400',
    code: 'text-rose-600/90 dark:text-rose-400/90',
  },
  muted: {
    ring: 'bg-[rgb(var(--background-secondary))] text-[rgb(var(--foreground-muted))]',
    code: 'text-[rgb(var(--foreground-muted))]',
  },
} as const

function ErrorShell({
  icon,
  code,
  title,
  tone = 'muted',
  children,
  action,
}: {
  icon: ReactNode
  code: string
  title: string
  tone?: keyof typeof TONES
  children: ReactNode
  action?: ReactNode
}) {
  const palette = TONES[tone]

  return (
    // Centres in the remaining viewport rather than in a small card, so
    // the page reads as a full stop rather than a footnote.
    <div className="flex min-h-[70vh] flex-col items-center justify-center px-4 text-center">
      <div
        className={cn(
          'flex size-24 items-center justify-center rounded-full sm:size-28',
          palette.ring
        )}
      >
        {icon}
      </div>

      <p
        className={cn(
          'mt-8 text-6xl font-black tracking-tighter tabular-nums sm:text-8xl',
          palette.code
        )}
      >
        {code}
      </p>

      <h1 className="mt-2 text-2xl font-bold tracking-tight text-[rgb(var(--foreground))] sm:text-3xl">
        {title}
      </h1>

      <div className="mt-3 max-w-lg text-base text-[rgb(var(--foreground-muted))]">
        {children}
      </div>

      <div className="mt-8 flex flex-col gap-3 sm:flex-row">
        {action ?? (
          <Button variant="outline" size="lg" onClick={() => window.history.back()}>
            Go back
          </Button>
        )}
      </div>
    </div>
  )
}

export function NotFoundPage() {
  useDocumentTitle('Page not found')
  return (
    <ErrorShell
      icon={<SearchX className="size-12 sm:size-14" aria-hidden="true" />}
      code="404"
      title="Page not found"
      action={
        <>
          <Button variant="outline" size="lg" onClick={() => window.history.back()}>
            Go back
          </Button>
          <Link to="/">
            <Button size="lg" fullWidth>
              Back to dashboard
            </Button>
          </Link>
        </>
      }
    >
      That page does not exist. It may have been moved, or the link may be wrong.
    </ErrorShell>
  )
}

export function ForbiddenPage({ requiredPermission }: { requiredPermission?: string }) {
  useDocumentTitle('Access denied')
  return (
    <ErrorShell
      icon={<ShieldX className="size-12 sm:size-14" aria-hidden="true" />}
      code="403"
      title="You do not have access"
      tone="danger"
      action={
        <>
          <Button variant="outline" size="lg" onClick={() => window.history.back()}>
            Go back
          </Button>
          <Link to="/">
            <Button size="lg" fullWidth>
              Back to dashboard
            </Button>
          </Link>
        </>
      }
    >
      Your role does not grant access to this page.
      {requiredPermission ? (
        <>
          {' '}
          It requires{' '}
          <code className="rounded-md bg-[rgb(var(--background-secondary))] px-2 py-1 text-sm font-semibold">
            {requiredPermission}
          </code>
          .
        </>
      ) : null}{' '}
      Ask an administrator if you need it.
    </ErrorShell>
  )
}

/** Router-level catch-all for unexpected render/loader errors. */
export function AppErrorPage({ error }: { error: Error }) {
  useDocumentTitle('Something went wrong')
  return (
    <ErrorShell
      icon={<OctagonAlert className="size-12 sm:size-14" aria-hidden="true" />}
      code="Error"
      title="Something went wrong"
      tone="danger"
      action={
        <Button size="lg" onClick={() => window.location.reload()}>
          Reload the page
        </Button>
      }
    >
      {error.message || 'An unexpected error occurred.'}
    </ErrorShell>
  )
}
