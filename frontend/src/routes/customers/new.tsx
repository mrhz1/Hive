import { createFileRoute } from '@tanstack/react-router'
import { RequirePermission } from '@/components/PermissionGate'
import { PageHeader } from '@/components/ui/Misc'
import { CustomerForm } from '@/features/customers/CustomerForm'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'

function NewCustomer() {
  useDocumentTitle('New customer')
  return (
    <div className="space-y-6">
      <PageHeader title="New customer" description="Add a customer record." />
      <CustomerForm />
    </div>
  )
}

export const Route = createFileRoute('/customers/new')({
  component: () => (
    <RequirePermission permission="customers:create">
      <NewCustomer />
    </RequirePermission>
  ),
})
