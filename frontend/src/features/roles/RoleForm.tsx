import { useNavigate } from '@tanstack/react-router'
import { Controller } from 'react-hook-form'
import { FormLayout, FullWidth } from '@/components/FormLayout'
import { TextField } from '@/components/ui/Field'
import { applyServerErrors, useApiForm } from '@/hooks/useApiForm'
import { roleHooks } from '@/hooks/useResources'
import { NAV_GROUPS, ZONE_STYLES } from '@/components/layout/navigation'
import { cn } from '@/lib/cn'
import {
  PERMISSION_SECTIONS,
  actionLabel,
  type Permission,
  type PermissionGroup,
} from '@/schemas/common'
import { roleFormSchema, type Role, type RoleFormValues } from '@/schemas/role'

const FIELD_NAMES = ['name', 'permissions'] as const

const EMPTY: RoleFormValues = { name: '', permissions: [] }

function PermissionTable({
  group,
  has,
  toggle,
  toggleRow,
}: {
  group: PermissionGroup
  has: (permission: Permission) => boolean
  toggle: (permission: Permission) => void
  toggleRow: (model: string, actions: readonly string[]) => void
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-[rgb(var(--border))]">
      <table className="w-full min-w-[28rem] border-collapse text-sm">
        <thead className="bg-[rgb(var(--background-secondary))]">
          <tr>
            <th
              scope="col"
              className="px-4 py-3 text-left text-xs font-semibold tracking-wider uppercase"
            >
              Resource
            </th>
            {group.actions.map((action) => (
              <th
                key={action}
                scope="col"
                className="px-4 py-3 text-center text-xs font-semibold tracking-wider uppercase"
              >
                {group.labels?.[action] ?? actionLabel(action)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[rgb(var(--border))]">
          {group.models.map((model) => (
            <tr
              key={model}
              className="transition-colors hover:bg-[rgb(var(--background-secondary))]"
            >
              <th scope="row" className="px-4 py-3 text-left font-medium">
                <button
                  type="button"
                  onClick={() => toggleRow(model, group.actions)}
                  className="capitalize underline-offset-2 hover:text-teal-600 hover:underline dark:hover:text-teal-400"
                >
                  {group.rowLabel ?? model}
                </button>
              </th>
              {group.actions.map((action) => {
                const permission = `${model}:${action}` as Permission
                return (
                  <td key={action} className="px-4 py-3 text-center">
                    <input
                      type="checkbox"
                      className="size-4 cursor-pointer rounded border-[rgb(var(--border))] accent-teal-600"
                      checked={has(permission)}
                      onChange={() => toggle(permission)}
                      aria-label={permission}
                    />
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PermissionMatrix({
  value,
  onChange,
  error,
}: {
  value: Permission[]
  onChange: (next: Permission[]) => void
  error?: string | undefined
}) {
  const has = (permission: Permission) => value.includes(permission)

  const toggle = (permission: Permission) => {
    onChange(
      has(permission)
        ? value.filter((p) => p !== permission)
        : [...value, permission].sort()
    )
  }

  const toggleRow = (model: string, actions: readonly string[]) => {
    const rowPermissions = actions.map((a) => `${model}:${a}` as Permission)
    const allSelected = rowPermissions.every(has)
    onChange(
      allSelected
        ? value.filter((p) => !rowPermissions.includes(p))
        : [...new Set([...value, ...rowPermissions])].sort()
    )
  }

  return (
    <fieldset className="w-full space-y-2">
      <legend className="ml-0.5 block text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
        Permissions
      </legend>
      <p className="px-1 text-[11px] text-[rgb(var(--foreground-muted))]">
        Grants are checked on every API call; unchecking one takes effect immediately.
      </p>

      {PERMISSION_SECTIONS.map((section) => {
        const nav = NAV_GROUPS.find((group) => group.id === section.id)
        return (
          <section key={section.id} className="space-y-2 pt-3">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-1">
              <span
                className={cn(
                  'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
                  nav?.tone ? ZONE_STYLES[nav.tone].badge : ''
                )}
              >
                {nav?.tag ? `${nav.tag} · ${nav.label}` : nav?.label}
              </span>
              <span className="text-[11px] text-[rgb(var(--foreground-muted))]">
                {section.description}
              </span>
            </div>
            {section.groups.map((group) => (
              <PermissionTable
                key={`${group.models.join()}:${group.actions.join()}`}
                group={group}
                has={has}
                toggle={toggle}
                toggleRow={toggleRow}
              />
            ))}
          </section>
        )
      })}

      {error ? (
        <div
          role="alert"
          className="flex items-center gap-1.5 px-1 text-[11px] font-semibold text-rose-600 dark:text-rose-400"
        >
          {error}
        </div>
      ) : null}
    </fieldset>
  )
}

export function RoleForm({ role }: { role?: Role }) {
  const mode = role ? 'edit' : 'create'
  const navigate = useNavigate()

  const create = roleHooks.useCreate()
  const update = roleHooks.useUpdate()

  const form = useApiForm(
    roleFormSchema,
    role ? { name: role.name, permissions: role.permissions } : EMPTY
  )
  const {
    control,
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = form

  const isSubmitting = create.isPending || update.isPending

  const onSubmit = handleSubmit(async (values) => {
    try {
      if (role) {
        await update.mutateAsync({ id: role.id, values })
      } else {
        await create.mutateAsync(values)
      }
      await navigate({ to: '/roles' })
    } catch (error) {
      applyServerErrors<RoleFormValues>(error, setError, FIELD_NAMES)
    }
  })

  return (
    <FormLayout
      mode={mode}
      entityLabel="role"
      cancelTo="/roles"
      isSubmitting={isSubmitting}
      onSubmit={onSubmit}
      footerNote={
        mode === 'create' ? 'Role names must be unique.' : `Editing ${role?.name}`
      }
    >
      <FullWidth>
        <TextField
          label="Name"
          required
          autoComplete="off"
          placeholder="support"
          error={errors.name?.message}
          {...register('name')}
        />
      </FullWidth>
      <FullWidth>
        <Controller
          control={control}
          name="permissions"
          render={({ field }) => (
            <PermissionMatrix
              value={field.value}
              onChange={field.onChange}
              error={errors.permissions?.message}
            />
          )}
        />
      </FullWidth>
    </FormLayout>
  )
}
