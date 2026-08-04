import { createFileRoute } from '@tanstack/react-router'
import { NotFoundPage } from '@/components/ErrorPages'
import { RequirePermission } from '@/components/PermissionGate'
import { PageHeader } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { CustomerForm } from '@/features/customers/CustomerForm'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { customerHooks } from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'

function EditCustomer() {
  const { customerId } = Route.useParams()
  const { data: customer, isLoading, error } = customerHooks.useDetail(customerId)

  useDocumentTitle(
    customer ? `Edit ${customer.first_name} ${customer.last_name}` : 'Edit customer'
  )

  if (isLoading) return <LoadingBlock label="Loading customer" />
  if (error instanceof ApiError && error.isNotFound) return <NotFoundPage />
  if (!customer) return <NotFoundPage />

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Edit ${customer.first_name} ${customer.last_name}`}
        description="Update this customer's details."
      />
      <CustomerForm customer={customer} />
    </div>
  )
}

export const Route = createFileRoute('/customers/$customerId/edit')({
  component: () => (
    <RequirePermission permission="customers:update">
      <EditCustomer />
    </RequirePermission>
  ),
})
