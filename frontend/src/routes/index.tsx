import { createFileRoute, Link } from '@tanstack/react-router'
import { ClipboardList, Shield, Users, UsersRound } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import { useCurrentUser, usePermissions } from '@/hooks/useCurrentUser'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { patientHooks, roleHooks, userHooks, useAuditLogs } from '@/hooks/useResources'
import type { Permission } from '@/schemas/common'

function StatCard({
  label,
  icon: Icon,
  count,
  isLoading,
  to,
}: {
  label: string
  icon: LucideIcon
  count: number | undefined
  isLoading: boolean
  to: string
}) {
  return (
    <Link to={to} className="block">
      <Card className="p-5 transition hover:border-teal-500 hover:shadow-md">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
            {label}
          </span>
          <Icon
            className="size-4 text-[rgb(var(--foreground-muted))]"
            aria-hidden="true"
          />
        </div>
        <div className="mt-3 text-3xl font-bold tabular-nums">
          {isLoading ? <Spinner size="sm" label={`Loading ${label}`} /> : (count ?? 0)}
        </div>
      </Card>
    </Link>
  )
}

function Dashboard() {
  useDocumentTitle('Dashboard')
  const { data: user } = useCurrentUser()
  const { can, permissions } = usePermissions()

  // Each list is fetched only if the user may read it -- firing a request
  // that is guaranteed to 403 would be noise in the logs and a wasted
  // Hive query.
  const users = userHooks.useList({ enabled: can('user:view') })
  const patients = patientHooks.useList({ enabled: can('patient:view') })
  const roles = roleHooks.useList({ enabled: can('role:view') })
  const logs = useAuditLogs({ limit: 5 }, can('log:view'))

  const cards: Array<{
    label: string
    icon: LucideIcon
    to: string
    permission: Permission
    count: number | undefined
    isLoading: boolean
  }> = [
    {
      label: 'Users',
      icon: Users,
      to: '/users',
      permission: 'user:view',
      count: users.data?.length,
      isLoading: users.isLoading,
    },
    {
      label: 'Patients',
      icon: UsersRound,
      to: '/patients',
      permission: 'patient:view',
      count: patients.data?.length,
      isLoading: patients.isLoading,
    },
    {
      label: 'Roles',
      icon: Shield,
      to: '/roles',
      permission: 'role:view',
      count: roles.data?.length,
      isLoading: roles.isLoading,
    },
  ]

  const visibleCards = cards.filter((card) => can(card.permission))

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Welcome, ${user?.first_name ?? 'there'}`}
        description="Overview of the records you have access to."
      />

      {visibleCards.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {visibleCards.map((card) => (
            <StatCard
              key={card.label}
              label={card.label}
              icon={card.icon}
              count={card.count}
              isLoading={card.isLoading}
              to={card.to}
            />
          ))}
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
            Your access
          </h2>
          <p className="mt-2 text-sm">
            Role:{' '}
            {user?.role_name ? (
              <Badge tone="info">{user.role_name}</Badge>
            ) : (
              <Badge tone="warning">none assigned</Badge>
            )}
          </p>
          {permissions.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {permissions.map((permission) => (
                <Badge key={permission}>{permission}</Badge>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-[rgb(var(--foreground-muted))]">
              You have no permissions yet. An administrator needs to assign you a role.
            </p>
          )}
        </Card>

        {can('log:view') ? (
          <Card className="p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
                Recent activity
              </h2>
              <Link
                to="/logs"
                className="text-xs font-semibold text-teal-600 underline-offset-2 hover:underline dark:text-teal-400"
              >
                View all
              </Link>
            </div>
            {logs.isLoading ? (
              <div className="py-6">
                <Spinner label="Loading recent activity" />
              </div>
            ) : logs.data && logs.data.length > 0 ? (
              <ul className="mt-3 flex flex-col gap-2">
                {logs.data.slice(0, 5).map((entry) => (
                  <li key={entry.id} className="flex items-center gap-2 text-sm">
                    <ClipboardList
                      className="size-3.5 shrink-0 text-[rgb(var(--foreground-muted))]"
                      aria-hidden="true"
                    />
                    <span className="font-semibold">{entry.action}</span>
                    <span className="truncate text-[rgb(var(--foreground-muted))]">
                      {entry.entity_type} · {entry.created_at}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-[rgb(var(--foreground-muted))]">
                No activity recorded yet.
              </p>
            )}
          </Card>
        ) : null}
      </div>
    </div>
  )
}

export const Route = createFileRoute('/')({
  component: Dashboard,
})
