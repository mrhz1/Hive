import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { FormLayout, FullWidth } from '@/components/FormLayout'
import {
  CheckboxField,
  SelectField,
  TextAreaField,
  TextField,
} from '@/components/ui/Field'
import { applyServerErrors, useApiForm } from '@/hooks/useApiForm'
import { customerHooks, useUploadFilesForCustomer } from '@/hooks/useResources'
import {
  CUSTOMER_STATUSES,
  customerFormSchema,
  type Customer,
  type CustomerFormValues,
} from '@/schemas/customer'
import { FilePicker } from './FilePicker'

const FIELD_NAMES = [
  'email',
  'first_name',
  'last_name',
  'phone_number',
  'address',
  'status',
  'is_active',
] as const

const EMPTY: CustomerFormValues = {
  email: '',
  first_name: '',
  last_name: '',
  phone_number: '',
  address: '',
  status: 'active',
  is_active: true,
}

function toFormValues(customer: Customer): CustomerFormValues {
  return {
    email: customer.email,
    first_name: customer.first_name,
    last_name: customer.last_name,
    phone_number: customer.phone_number,
    address: customer.address ?? '',
    status: customer.status,
    is_active: customer.is_active,
  }
}

/** Same component for create and edit -- see UserForm for the rationale. */
export function CustomerForm({ customer }: { customer?: Customer }) {
  const mode = customer ? 'edit' : 'create'
  const navigate = useNavigate()

  const create = customerHooks.useCreate()
  const update = customerHooks.useUpdate()
  const uploadFiles = useUploadFilesForCustomer()

  // Staged rather than uploaded on pick: on create there is no customer
  // id to attach them to until the record has been saved.
  const [pendingFiles, setPendingFiles] = useState<File[]>([])

  const form = useApiForm(customerFormSchema, customer ? toFormValues(customer) : EMPTY)
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = form

  const isSubmitting = create.isPending || update.isPending || uploadFiles.isPending

  const onSubmit = handleSubmit(async (values) => {
    let customerId: string

    try {
      if (customer) {
        await update.mutateAsync({ id: customer.id, values })
        customerId = customer.id
      } else {
        const created = await create.mutateAsync(values)
        customerId = created.id
      }
    } catch (error) {
      applyServerErrors<CustomerFormValues>(error, setError, FIELD_NAMES)
      return
    }

    // Uploaded after the record is saved, and deliberately outside the
    // try above: the customer already exists at this point, so a failed
    // upload must not look like the save failed. The mutation toasts its
    // own error and the files stay staged on the page.
    if (pendingFiles.length > 0) {
      try {
        await uploadFiles.mutateAsync({ customerId, files: pendingFiles })
        setPendingFiles([])
      } catch {
        return
      }
    }

    await navigate({ to: '/customers' })
  })

  return (
    <FormLayout
      mode={mode}
      entityLabel="customer"
      cancelTo="/customers"
      isSubmitting={isSubmitting}
      onSubmit={onSubmit}
      footerNote={
        mode === 'create'
          ? 'Email and phone number must be unique.'
          : `Editing ${customer?.email}`
      }
    >
      <TextField
        label="Email"
        type="email"
        required
        autoComplete="off"
        placeholder="acme@example.com"
        error={errors.email?.message}
        {...register('email')}
      />
      <TextField
        label="Phone number"
        required
        autoComplete="off"
        placeholder="+1 555 010 0100"
        error={errors.phone_number?.message}
        {...register('phone_number')}
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
        options={CUSTOMER_STATUSES.map((s) => ({ value: s, label: s }))}
        error={errors.status?.message}
        {...register('status')}
      />
      <div className="hidden sm:block" aria-hidden="true" />
      <FullWidth>
        <TextAreaField
          label="Address"
          placeholder="1 Industrial Way, Springfield"
          error={errors.address?.message}
          {...register('address')}
        />
      </FullWidth>
      <FullWidth>
        <CheckboxField
          label="Active"
          error={errors.is_active?.message}
          {...register('is_active')}
        />
      </FullWidth>
      <FullWidth>
        <div className="border-t border-[rgb(var(--border))] pt-6">
          <FilePicker
            files={pendingFiles}
            onFilesChange={setPendingFiles}
            disabled={isSubmitting}
            hint={
              mode === 'create'
                ? 'Uploaded once the customer is created. Choose a folder to include everything inside it.'
                : 'Added to this customer on save. Existing documents are managed on the Files page.'
            }
          />
        </div>
      </FullWidth>
    </FormLayout>
  )
}
