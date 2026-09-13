import { SelectField } from '@/components/ui/Field'
import { Card } from '@/components/ui/Misc'
import { userHooks } from '@/hooks/useResources'
import { userLabel } from '@/schemas/user'

export function AssigneeSelect({
  value,
  onChange,
  disabled,
  hint,
}: {
  value: string
  onChange: (userId: string) => void
  disabled?: boolean
  hint?: string
}) {
  const usersQuery = userHooks.useList()
  const users = usersQuery.data ?? []

  const options = users
    .filter((user) => user.is_active || user.id === value)
    .map((user) => ({ value: user.id, label: userLabel(user) }))

  return (
    <SelectField
      label="Assigned to"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled || usersQuery.isLoading}
      options={options}
      placeholder={usersQuery.isLoading ? 'Loading users…' : 'Nobody yet'}
      hint={
        hint ??
        'This user is emailed when documents finish uploading, and when an upload fails.'
      }
    />
  )
}

export function AssigneeCard({
  value,
  onChange,
  disabled,
}: {
  value: string
  onChange: (userId: string) => void
  disabled?: boolean
}) {
  return (
    <Card className="p-5">
      <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
        Assignment
      </h2>
      <div className="mt-4 max-w-md">
        <AssigneeSelect value={value} onChange={onChange} disabled={disabled} />
      </div>
    </Card>
  )
}
