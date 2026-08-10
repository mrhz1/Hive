import { AlertCircle } from 'lucide-react'
import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react'
import { cn } from '@/lib/cn'
import { inputVariants, selectVariants } from './Field.styles'

export function FormField({
  label,
  error,
  hint,
  required,
  htmlFor,
  children,
}: {
  label: string
  error?: string | undefined
  hint?: string
  required?: boolean
  htmlFor: string
  children: ReactNode
}) {
  return (
    <div className="w-full space-y-2">
      <label
        htmlFor={htmlFor}
        className="ml-0.5 block text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase"
      >
        {label}
        {required ? (
          <span className="ml-0.5 text-rose-500" aria-hidden="true">
            *
          </span>
        ) : null}
      </label>

      {children}

      {error ? (
        <div
          role="alert"
          className="animate-in fade-in slide-in-from-top-1 flex items-center gap-1.5 px-1 text-[11px] font-semibold text-rose-600 dark:text-rose-400"
        >
          <AlertCircle size={12} strokeWidth={2.5} className="shrink-0" />
          <span className="whitespace-pre-line">{error}</span>
        </div>
      ) : hint ? (
        <p className="px-1 text-[11px] text-[rgb(var(--foreground-muted))]">{hint}</p>
      ) : null}
    </div>
  )
}

export type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> & {
  label: string
  error?: string | undefined
  hint?: string
}

export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, error, hint, className, required, ...props },
  ref
) {
  const id = useId()
  return (
    <FormField label={label} error={error} hint={hint} required={required} htmlFor={id}>
      <input
        {...props}
        id={id}
        ref={ref}
        required={required}
        aria-invalid={Boolean(error)}
        className={cn(inputVariants({ state: error ? 'error' : 'default' }), className)}
      />
    </FormField>
  )
})

export type SelectFieldProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id'> & {
  label: string
  error?: string | undefined
  hint?: string
  options: ReadonlyArray<{ value: string; label: string }>
  placeholder?: string
  placeholderDisabled?: boolean
}

export const SelectField = forwardRef<HTMLSelectElement, SelectFieldProps>(
  function SelectField(
    {
      label,
      error,
      hint,
      options,
      placeholder,
      placeholderDisabled,
      className,
      required,
      ...props
    },
    ref
  ) {
    const id = useId()
    return (
      <FormField label={label} error={error} hint={hint} required={required} htmlFor={id}>
        <select
          {...props}
          id={id}
          ref={ref}
          required={required}
          aria-invalid={Boolean(error)}
          className={cn(
            selectVariants({ state: error ? 'error' : 'default' }),
            className
          )}
        >
          {placeholder ? (
            <option value="" disabled={placeholderDisabled}>
              {placeholder}
            </option>
          ) : null}
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </FormField>
    )
  }
)

export type TextAreaFieldProps = Omit<
  TextareaHTMLAttributes<HTMLTextAreaElement>,
  'id'
> & {
  label: string
  error?: string | undefined
  hint?: string
}

export const TextAreaField = forwardRef<HTMLTextAreaElement, TextAreaFieldProps>(
  function TextAreaField({ label, error, hint, className, required, ...props }, ref) {
    const id = useId()
    return (
      <FormField label={label} error={error} hint={hint} required={required} htmlFor={id}>
        <textarea
          {...props}
          id={id}
          ref={ref}
          required={required}
          aria-invalid={Boolean(error)}
          className={cn(
            inputVariants({ state: error ? 'error' : 'default' }),
            'min-h-24',
            className
          )}
        />
      </FormField>
    )
  }
)

export type CheckboxFieldProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  'id' | 'type'
> & {
  label: string
  description?: string
  error?: string | undefined
}

export const CheckboxField = forwardRef<HTMLInputElement, CheckboxFieldProps>(
  function CheckboxField({ label, description, error, className, ...props }, ref) {
    const id = useId()
    const errorId = `${id}-error`

    return (
      <div className="w-full space-y-2">
        <div className="flex items-start gap-3">
          <input
            {...props}
            id={id}
            ref={ref}
            type="checkbox"
            aria-invalid={Boolean(error)}
            aria-describedby={error ? errorId : undefined}
            className={cn(
              'mt-0.5 size-4 shrink-0 cursor-pointer rounded border-[rgb(var(--border))] accent-teal-600',
              className
            )}
          />
          <div className="flex flex-col">
            <label htmlFor={id} className="cursor-pointer text-sm font-medium">
              {label}
            </label>
            {description ? (
              <span className="text-xs text-[rgb(var(--foreground-muted))]">
                {description}
              </span>
            ) : null}
          </div>
        </div>
        {error ? (
          <div
            id={errorId}
            role="alert"
            className="animate-in fade-in slide-in-from-top-1 flex items-center gap-1.5 px-1 text-[11px] font-semibold text-rose-600 dark:text-rose-400"
          >
            <AlertCircle size={12} strokeWidth={2.5} className="shrink-0" />
            <span>{error}</span>
          </div>
        ) : null}
      </div>
    )
  }
)
