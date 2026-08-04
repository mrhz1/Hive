import { useNavigate } from '@tanstack/react-router'
import { FormLayout, FullWidth } from '@/components/FormLayout'
import { CheckboxField, SelectField, TextField } from '@/components/ui/Field'
import { applyServerErrors, useApiForm } from '@/hooks/useApiForm'
import { roleHooks, userHooks } from '@/hooks/useResources'
import {
  USER_STATUSES,
  userFormSchema,
  type User,
  type UserFormValues,
} from '@/schemas/user'

const FIELD_NAMES = [
  'username',
  'email',
  'first_name',
  'last_name',
  'status',
  'is_active',
  'role_id',
] as const

const EMPTY: UserFormValues = {
  username: '',
  email: '',
  first_name: '',
  last_name: '',
  status: 'active',
  is_active: true,
  role_id: '',
}

function toFormValues(user: User): UserFormValues {
  return {
    username: user.username,
    email: user.email,
    first_name: user.first_name,
    last_name: user.last_name,
    status: user.status,
    is_active: user.is_active,
    role_id: user.role_id ?? '',
  }
}

/**
 * One form for both create and edit. The route decides which by passing
 * `user`; everything else -- validation, layout, submit handling -- is
 * identical, so there is no second implementation to drift.
 */
export function UserForm({ user }: { user?: User }) {
  const mode = user ? 'edit' : 'create'
  const navigate = useNavigate()

  const create = userHooks.useCreate()
  const update = userHooks.useUpdate()
  const { data: roles, isLoading: rolesLoading } = roleHooks.useList()

  const form = useApiForm(userFormSchema, user ? toFormValues(user) : EMPTY)
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = form

  const isSubmitting = create.isPending || update.isPending

  const onSubmit = handleSubmit(async (values) => {
    try {
      if (user) {
        await update.mutateAsync({ id: user.id, values })
      } else {
        await create.mutateAsync(values)
      }
      await navigate({ to: '/users' })
    } catch (error) {
      // Toast already fired in the mutation; additionally pin the message
      // to its field when the server identified one.
      applyServerErrors<UserFormValues>(error, setError, FIELD_NAMES)
    }
  })

  const roleOptions = (roles ?? []).map((role) => ({
    value: role.id,
    label: role.name,
  }))

  return (
    <FormLayout
      mode={mode}
      entityLabel="user"
      cancelTo="/users"
      isSubmitting={isSubmitting}
      onSubmit={onSubmit}
      footerNote={
        mode === 'create'
          ? 'Username and email must be unique.'
          : `Editing ${user?.username}`
      }
    >
      <TextField
        label="Username"
        required
        autoComplete="off"
        placeholder="jdoe"
        error={errors.username?.message}
        {...register('username')}
      />
      <TextField
        label="Email"
        type="email"
        required
        autoComplete="off"
        placeholder="jdoe@example.com"
        error={errors.email?.message}
        {...register('email')}
      />
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
      <SelectField
        label="Status"
        required
        options={USER_STATUSES.map((s) => ({ value: s, label: s }))}
        error={errors.status?.message}
        {...register('status')}
      />
      <SelectField
        label="Role"
        required
        // Disabled so "no role" cannot be chosen back: every user must
        // have one. It still shows while role_id is empty, and the schema
        // rejects submitting in that state.
        placeholder={rolesLoading ? 'Loading roles…' : 'Select a role...'}
        placeholderDisabled
        options={roleOptions}
        hint="Determines what this user can do in the dashboard."
        error={errors.role_id?.message}
        disabled={rolesLoading}
        {...register('role_id')}
      />
      <FullWidth>
        <CheckboxField
          label="Active"
          description="Inactive users are rejected by the API even if they have a role."
          error={errors.is_active?.message}
          {...register('is_active')}
        />
      </FullWidth>
    </FormLayout>
  )
}
