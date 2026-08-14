import { Check, ChevronDown, Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Spinner } from '@/components/ui/Spinner'
import { patientHooks } from '@/hooks/useResources'
import { cn } from '@/lib/cn'
import { patientMatches, patientName, type Patient } from '@/schemas/patient'

/**
 * Pick a patient by typing, not by scrolling.
 *
 * A plain <select> is fine for a handful of options and unusable at a
 * few hundred: the only way to a patient near the end of the list is to
 * scroll to them, and the list is in whatever order the API returned.
 * This filters as you type on name, id, email or phone -- the id
 * included because that is what is written on the folder somebody is
 * holding.
 */
export function PatientCombobox({
  value,
  onChange,
  label = 'Patient',
  required = false,
  disabled = false,
  hint,
}: {
  value: string
  onChange: (patientId: string) => void
  label?: string
  required?: boolean
  disabled?: boolean
  hint?: string
}) {
  const { data: patients, isLoading } = patientHooks.useList()

  const [query, setQuery] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(0)

  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const all = useMemo(() => patients ?? [], [patients])
  const selected = all.find((patient) => patient.id === value)

  const results = useMemo(
    () => all.filter((patient) => patientMatches(patient, query)),
    [all, query]
  )

  // Clamped rather than reset: the list shrinks as the query narrows, and
  // the highlight must not be left pointing past the end of it.
  const active = Math.min(highlighted, Math.max(0, results.length - 1))

  useEffect(() => {
    if (!isOpen) return

    function onPointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsOpen(false)
        setQuery('')
      }
    }

    window.document.addEventListener('mousedown', onPointerDown)
    return () => window.document.removeEventListener('mousedown', onPointerDown)
  }, [isOpen])

  function choose(patient: Patient) {
    onChange(patient.id)
    setQuery('')
    setIsOpen(false)
    inputRef.current?.blur()
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      setIsOpen(false)
      setQuery('')
      return
    }

    if (!isOpen && (event.key === 'ArrowDown' || event.key === 'Enter')) {
      setIsOpen(true)
      return
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setHighlighted(Math.min(results.length - 1, active + 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setHighlighted(Math.max(0, active - 1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const patient = results[active]
      if (patient) choose(patient)
    }
  }

  // The input shows what is typed while searching, and the chosen
  // patient the rest of the time -- so the field always says what is
  // selected without a second line of text under it.
  const shown = isOpen ? query : selected ? patientLabel(selected) : ''

  return (
    <div className="w-full space-y-2" ref={containerRef}>
      <label
        className="ml-0.5 block text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase"
        htmlFor="patient-combobox"
      >
        {label}
        {required ? <span className="ml-1 text-[rgb(var(--danger))]">*</span> : null}
      </label>

      <div className="relative">
        <Search
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[rgb(var(--foreground-muted))]"
          aria-hidden="true"
        />
        <input
          id="patient-combobox"
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded={isOpen}
          aria-controls="patient-combobox-list"
          aria-autocomplete="list"
          autoComplete="off"
          disabled={disabled || isLoading}
          value={shown}
          placeholder={
            isLoading ? 'Loading patients…' : 'Search by name, id, email or phone'
          }
          onChange={(event) => {
            setQuery(event.target.value)
            setHighlighted(0)
            setIsOpen(true)
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={onKeyDown}
          className={cn(
            'w-full rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))]',
            'py-2 pr-9 pl-9 text-sm',
            'focus:border-[rgb(var(--primary))] focus:ring-1 focus:ring-[rgb(var(--primary))] focus:outline-none',
            'disabled:cursor-not-allowed disabled:opacity-60'
          )}
        />
        <ChevronDown
          className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-[rgb(var(--foreground-muted))]"
          aria-hidden="true"
        />

        {isOpen ? (
          <ul
            id="patient-combobox-list"
            role="listbox"
            aria-label="Patients"
            className={cn(
              'absolute z-20 mt-1 max-h-64 w-full overflow-y-auto',
              'rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] shadow-lg'
            )}
          >
            {isLoading ? (
              <li className="p-4">
                <Spinner size="sm" label="Loading patients" />
              </li>
            ) : results.length === 0 ? (
              <li className="px-3 py-4 text-center text-xs text-[rgb(var(--foreground-muted))]">
                No patient matches “{query}”.
              </li>
            ) : (
              results.map((patient, index) => {
                const isSelected = patient.id === value
                return (
                  <li key={patient.id} role="option" aria-selected={isSelected}>
                    <button
                      type="button"
                      // Chosen on mousedown: a click would land after the
                      // blur that closes the list.
                      onMouseDown={(event) => {
                        event.preventDefault()
                        choose(patient)
                      }}
                      onMouseEnter={() => setHighlighted(index)}
                      className={cn(
                        'flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm',
                        index === active
                          ? 'bg-[rgb(var(--surface-muted))]'
                          : 'bg-transparent'
                      )}
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-semibold">
                          {patientName(patient)}
                        </span>
                        <span className="block truncate text-xs text-[rgb(var(--foreground-muted))]">
                          {patient.ptemail || patient.ptphone || 'No contact details'}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-2 font-mono text-xs tabular-nums">
                        {patient.id}
                        {isSelected ? (
                          <Check className="size-3.5" aria-hidden="true" />
                        ) : null}
                      </span>
                    </button>
                  </li>
                )
              })
            )}
          </ul>
        ) : null}
      </div>

      {hint ? (
        <p className="px-1 text-[11px] text-[rgb(var(--foreground-muted))]">{hint}</p>
      ) : null}
    </div>
  )
}

function patientLabel(patient: Patient): string {
  return `${patientName(patient)} (${patient.id})`
}
