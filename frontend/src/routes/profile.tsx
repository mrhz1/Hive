import { createFileRoute } from '@tanstack/react-router'
import { Badge, Card, DescriptionItem, PageHeader } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { useCurrentUser } from '@/hooks/useCurrentUser'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'

function Profile() {
  useDocumentTitle('Profile')

  const { data: user, isLoading } = useCurrentUser()

  if (isLoading) return <LoadingBlock label="Loading your profile" />
  if (!user) return null

  return (
    <div className="space-y-6">
      <PageHeader
        title="Your Profile"
        description="Your account as an administrator set it up. To change your name or email, ask an administrator; changes are made on the Users page and recorded in the audit log."
      />

      <Card className="p-6">
        <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
          Account
        </h2>
        <dl className="mt-4">
          <DescriptionItem label="Username">{user.username}</DescriptionItem>
          <DescriptionItem label="Name">
            {[user.first_name, user.last_name].filter(Boolean).join(' ') || '—'}
          </DescriptionItem>
          <DescriptionItem label="Email">{user.email}</DescriptionItem>
          <DescriptionItem label="Role">
            {user.role_name ? (
              <Badge tone="info">{user.role_name}</Badge>
            ) : (
              <Badge tone="warning">No role</Badge>
            )}
          </DescriptionItem>
          <DescriptionItem label="Status">
            <Badge tone={user.is_active ? 'success' : 'danger'}>
              {user.is_active || user.status === 'inactive'
                ? user.status
                : `${user.status} (inactive)`}
            </Badge>
          </DescriptionItem>
          <DescriptionItem label="Permissions">
            {user.permissions.length === 0 ? (
              <span className="text-[rgb(var(--foreground-muted))]">None</span>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {user.permissions.map((permission) => (
                  <Badge key={permission}>{permission}</Badge>
                ))}
              </div>
            )}
          </DescriptionItem>
          <DescriptionItem label="Member since">{user.created_at}</DescriptionItem>
        </dl>
      </Card>
    </div>
  )
}

export const Route = createFileRoute('/profile')({
  component: Profile,
})
