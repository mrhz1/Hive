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

/**
 * react-hook-form wired to a zod schema with live validation.
 *
 * mode 'onChange' + reValidateMode 'onChange' is what makes an error
 * appear as soon as a character makes the value invalid, and clear as
 * soon as it becomes valid -- rather than only on blur or submit.
 * Submitting still revalidates everything, so an untouched empty required
 * field is caught too.
 */
export function useApiForm<TValues extends FieldValues>(
  schema: z.ZodType<TValues, TValues>,
  defaultValues: DefaultValues<TValues>,
  options?: Omit<UseFormProps<TValues>, 'resolver' | 'defaultValues' | 'mode'>
) {
  return useForm<TValues>({
    // zodResolver's overloads cannot see through the generic `schema`
    // here; the call is checked at each concrete call site instead.
    resolver: zodResolver(schema as never),
    defaultValues,
    mode: 'onChange',
    reValidateMode: 'onChange',
    ...options,
  })
}

/**
 * Projects a server rejection onto the form.
 *
 * A 422 carries per-field messages, and a 409 uniqueness conflict names
 * the offending field in its detail text. Both belong under the input
 * that caused them, not only in a toast the user has to translate back to
 * a field themselves.
 *
 * Returns true when the error was attributed to a specific field.
 */
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
