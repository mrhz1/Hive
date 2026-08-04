import { createRootRoute, Outlet } from '@tanstack/react-router'
import { AppErrorPage, NotFoundPage } from '@/components/ErrorPages'
import { AppShell } from '@/components/layout/AppShell'
import { LoadingBlock } from '@/components/ui/Spinner'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Misc'
import { useCurrentUser } from '@/hooks/useCurrentUser'
import { ApiError } from '@/lib/api/client'

/**
 * Gates the whole app on knowing who the caller is.
 *
 * There is no login screen, so identity comes from the API. Until /me
 * resolves the shell cannot decide which menu items or actions to show,
 * and rendering an empty sidebar first would flash the wrong UI.
 */
function IdentityGate({ children }: { children: React.ReactNode }) {
  const { data: user, isLoading, error, refetch, isFetching } = useCurrentUser()

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
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
          <h1 className="text-lg font-semibold">
            {isIdentityProblem ? 'We could not identify you' : 'Cannot reach the API'}
          </h1>
          <p className="mt-2 text-sm text-[rgb(var(--foreground-muted))]">
            {apiError?.message ?? 'The API did not respond.'}
          </p>
          {isIdentityProblem ? (
            <p className="mt-3 text-xs text-[rgb(var(--foreground-muted))]">
              Locally, set <code>VITE_DEV_USER_ID</code> in{' '}
              <code>frontend/.env.local</code> to a user id from <code>make init</code>.
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
  // Rendered inside the root component's Outlet, which already supplies
  // IdentityGate + AppShell -- wrapping again would nest a second shell
  // and duplicate the sidebar.
  notFoundComponent: NotFoundPage,
  errorComponent: ({ error }) => <AppErrorPage error={error} />,
})
