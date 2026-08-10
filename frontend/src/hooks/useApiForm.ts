import { zodResolver } from '@hookform/resolvers/zod'
import {
  useForm,
  type DefaultValues,
  type FieldValues,
  type Path,
  type UseFormProps,
} from 'react-hook-form'
import type { z } from 'zod'
import { ApiError } from '@/lib/api/client'

export function useApiForm<TValues extends FieldValues>(
  schema: z.ZodType<TValues, TValues>,
  defaultValues: DefaultValues<TValues>,
  options?: Omit<UseFormProps<TValues>, 'resolver' | 'defaultValues' | 'mode'>
) {
  return useForm<TValues>({
    resolver: zodResolver(schema as never),
    defaultValues,
    mode: 'onChange',
    reValidateMode: 'onChange',
    ...options,
  })
}

export function applyServerErrors<TValues extends FieldValues>(
  error: unknown,
  setError: (name: Path<TValues>, error: { type: string; message: string }) => void,
  fieldNames: ReadonlyArray<Path<TValues>>
): boolean {
  if (!(error instanceof ApiError)) return false

  let attributed = false

  for (const fieldError of error.fieldErrors) {
    const match = fieldNames.find((name) => name === fieldError.field)
    if (match) {
      setError(match, { type: 'server', message: fieldError.message })
      attributed = true
    }
  }

  if (!attributed && error.isConflict) {
    // e.g. "Username 'jdoe' already exists" / "Email '...' already exists"
    const detail = error.message.toLowerCase()
    const match = fieldNames.find((name) =>
      detail.startsWith(String(name).replace(/_/g, ' '))
    )
    if (match) {
      setError(match, { type: 'server', message: error.message })
      attributed = true
    }
  }

  return attributed
}
