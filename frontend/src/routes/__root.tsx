import { createRootRoute, Outlet } from '@tanstack/react-router'
import { AppErrorPage, NotFoundPage } from '@/components/ErrorPages'
import { AppShell } from '@/components/layout/AppShell'
import { Logo } from '@/components/Logo'
import { LoadingBlock } from '@/components/ui/Spinner'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Misc'
import { useCurrentUser } from '@/hooks/useCurrentUser'
import { ApiError } from '@/lib/api/client'

function IdentityGate({ children }: { children: React.ReactNode }) {
  const { data: user, isLoading, error, refetch, isFetching } = useCurrentUser()

  if (isLoading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6">
        <Logo className="size-14" label="Hive Admin" />
        <LoadingBlock label="Loading your account" />
      </div>
    )
  }

  if (error || !user) {
    const apiError = error instanceof ApiError ? error : null
    const isIdentityProblem = apiError?.isUnauthenticated ?? false

    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <Card className="w-full max-w-md p-8 text-center">
          <Logo className="mx-auto mb-4 size-12" label="Hive Admin" />
          <h1 className="text-lg font-semibold">
            {isIdentityProblem ? 'We could not identify you' : 'Cannot reach the API'}
          </h1>
          <p className="mt-2 text-sm text-[rgb(var(--foreground-muted))]">
            {apiError?.message ?? 'The API did not respond.'}
          </p>
          {isIdentityProblem ? (
            <p className="mt-3 text-xs text-[rgb(var(--foreground-muted))]">
              Locally, set <code>VITE_DEV_USERNAME</code> in{' '}
              <code>frontend/.env.local</code> to a username from <code>make init</code>.
              On Cloudera AI the platform supplies the identity instead.
            </p>
          ) : null}
          <Button className="mt-6" isLoading={isFetching} onClick={() => void refetch()}>
            Try again
          </Button>
        </Card>
      </div>
    )
  }

  return <AppShell>{children}</AppShell>
}

export const Route = createRootRoute({
  component: () => (
    <IdentityGate>
      <Outlet />
    </IdentityGate>
  ),
  notFoundComponent: NotFoundPage,
  errorComponent: ({ error }) => <AppErrorPage error={error} />,
})
