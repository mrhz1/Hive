import { createFileRoute } from '@tanstack/react-router'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/Field'
import { Badge, Card, DescriptionItem, PageHeader } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { applyServerErrors, useApiForm } from '@/hooks/useApiForm'
import { useCurrentUser, useUpdateProfile } from '@/hooks/useCurrentUser'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { profileFormSchema, type ProfileFormValues } from '@/schemas/user'

const FIELD_NAMES = ['first_name', 'last_name', 'email'] as const

function Profile() {
  useDocumentTitle('Profile')

  const { data: user, isLoading } = useCurrentUser()
  const updateProfile = useUpdateProfile()

  const form = useApiForm(profileFormSchema, {
    first_name: user?.first_name ?? '',
    last_name: user?.last_name ?? '',
    email: user?.email ?? '',
  })

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isDirty },
  } = form

  if (isLoading) return <LoadingBlock label="Loading your profile" />
  if (!user) return null

  const onSubmit = handleSubmit(async (values) => {
    try {
      await updateProfile.mutateAsync(values)
    } catch (error) {
      applyServerErrors<ProfileFormValues>(error, setError, FIELD_NAMES)
    }
  })

  return (
    <div className="space-y-6">
      <PageHeader
        title="Your Profile"
        description="Update your own details. Role and status are managed by an administrator."
      />

      <form
        onSubmit={onSubmit}
        noValidate
        className="space-y-6 rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-6 shadow-sm"
      >
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          <TextField
            label="First name"
            required
            error={errors.first_name?.message}
            {...register('first_name')}
          />
          <TextField
            label="Last name"
            required
            error={errors.last_name?.message}
            {...register('last_name')}
          />
          <div className="sm:col-span-2">
            <TextField
              label="Email"
              type="email"
              required
              error={errors.email?.message}
              {...register('email')}
            />
          </div>
        </div>

        <div className="flex justify-end border-t border-[rgb(var(--border))] pt-6">
          <Button type="submit" isLoading={updateProfile.isPending} disabled={!isDirty}>
            {updateProfile.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      </form>

      <Card className="p-6">
        <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
          Account
        </h2>
        <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
          These are set by an administrator and cannot be changed here.
        </p>
        <dl className="mt-4">
          <DescriptionItem label="Username">{user.username}</DescriptionItem>
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
