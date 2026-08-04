import { createFileRoute, Link } from '@tanstack/react-router'
import { NotFoundPage } from '@/components/ErrorPages'
import { RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { Badge, Card, DescriptionItem, PageHeader } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useAuditLog } from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'

/** Renders old_values/new_values, which arrive as arbitrary JSON objects. */
function ValueBlock({
  title,
  values,
}: {
  title: string
  values: Record<string, unknown> | null | undefined
}) {
  return (
    <Card className="p-6">
      <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
        {title}
      </h2>
      {values == null ? (
        <p className="mt-2 text-sm text-[rgb(var(--foreground-muted))]">
          None — expected for {title === 'Before' ? 'a create' : 'a delete'}.
        </p>
      ) : (
        <dl className="mt-2">
          {Object.entries(values).map(([key, value]) => (
            <DescriptionItem key={key} label={key}>
              {value === null || value === undefined ? (
                <span className="text-[rgb(var(--foreground-muted))]">null</span>
              ) : (
                String(value)
              )}
            </DescriptionItem>
          ))}
        </dl>
      )}
    </Card>
  )
}

function LogDetail() {
  const { logId } = Route.useParams()
  const { data: entry, isLoading, error } = useAuditLog(logId)

  useDocumentTitle(entry ? `${entry.action} ${entry.entity_type}` : 'Audit entry')

  if (isLoading) return <LoadingBlock label="Loading audit entry" />
  if (error instanceof ApiError && error.isNotFound) return <NotFoundPage />
  if (!entry) return <NotFoundPage />

  return (
    <div className="space-y-6">
      <PageHeader
        title={`${entry.action} ${entry.entity_type}`}
        description={`Recorded ${entry.created_at}`}
        actions={
          <Link to="/logs">
            <Button variant="outline">Back to log</Button>
          </Link>
        }
      />

      <Card className="p-6">
        <dl>
          <DescriptionItem label="Action">
            <Badge
              tone={
                entry.action === 'CREATE'
                  ? 'success'
                  : entry.action === 'DELETE'
                    ? 'danger'
                    : 'info'
              }
            >
              {entry.action}
            </Badge>
          </DescriptionItem>
          <DescriptionItem label="Entity type">{entry.entity_type}</DescriptionItem>
          <DescriptionItem label="Record id">
            <code className="text-xs break-all">{entry.entity_id}</code>
          </DescriptionItem>
          <DescriptionItem label="Entry id">
            <code className="text-xs break-all">{entry.id}</code>
          </DescriptionItem>
          <DescriptionItem label="Recorded at">{entry.created_at}</DescriptionItem>
        </dl>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <ValueBlock title="Before" values={entry.old_values} />
        <ValueBlock title="After" values={entry.new_values} />
      </div>
    </div>
  )
}

export const Route = createFileRoute('/logs/$logId')({
  component: () => (
    <RequirePermission permission="logs:read">
      <LogDetail />
    </RequirePermission>
  ),
})
