import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Misc'
import { TextField } from '@/components/ui/Field'
import { LoadingBlock } from '@/components/ui/Spinner'
import { patientHooks } from '@/hooks/useResources'
import { cn } from '@/lib/cn'
import { patientName, type Patient } from '@/schemas/patient'

function matches(patient: Patient, query: string): boolean {
  const haystack = [
    patient.id,
    patient.fstname,
    patient.lstname,
    patient.ptemail,
    patient.ptphone,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()

  return haystack.includes(query)
}

export function ExistingPatientPicker({
  onSelect,
  isBusy,
}: {
  onSelect: (patient: Patient) => void
  isBusy?: boolean
}) {
  const { data: patients, isLoading, error } = patientHooks.useList()
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<string | undefined>(undefined)

  const results = useMemo(() => {
    const all = patients ?? []
    const trimmed = query.trim().toLowerCase()
    if (!trimmed) return all
    return all.filter((patient) => matches(patient, trimmed))
  }, [patients, query])

  const selected = results.find((patient) => patient.id === selectedId)

  if (isLoading) return <LoadingBlock label="Loading patients" />

  if (error) {
    return (
      <Card className="p-5 text-sm text-[rgb(var(--danger))]">
        Could not load patients. Try again, or create a new patient instead.
      </Card>
    )
  }

  if ((patients ?? []).length === 0) {
    return (
      <Card className="p-5 text-sm text-[rgb(var(--foreground-muted))]">
        There are no patients on file yet. Switch to <strong>New patient</strong>{' '}
        to create the first one.
      </Card>
    )
  }

  return (
    <Card className="space-y-4 p-5">
      <TextField
        label="Find a patient"
        placeholder="Name, patient id, email or phone"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        hint={`${results.length} of ${(patients ?? []).length} patients`}
      />

      {results.length === 0 ? (
        <p className="py-6 text-center text-sm text-[rgb(var(--foreground-muted))]">
          No patient matches "{query}".
        </p>
      ) : (
        <ul
          className="max-h-80 divide-y divide-[rgb(var(--border))] overflow-y-auto rounded-lg border border-[rgb(var(--border))]"
          aria-label="Patients"
        >
          {results.map((patient) => {
            const isSelected = patient.id === selectedId
            return (
              <li key={patient.id}>
                <button
                  type="button"
                  aria-pressed={isSelected}
                  onClick={() => setSelectedId(patient.id)}
                  className={cn(
                    'flex w-full items-center justify-between gap-4 px-4 py-3 text-left text-sm transition-colors',
                    isSelected
                      ? 'bg-[rgb(var(--primary))] text-[rgb(var(--primary-foreground))]'
                      : 'hover:bg-[rgb(var(--surface-muted))]'
                  )}
                >
                  <span className="min-w-0">
                    <span className="block truncate font-semibold">
                      {patientName(patient)}
                    </span>
                    <span
                      className={cn(
                        'block truncate text-xs',
                        isSelected
                          ? 'text-[rgb(var(--primary-foreground))] opacity-80'
                          : 'text-[rgb(var(--foreground-muted))]'
                      )}
                    >
                      {patient.ptemail || patient.ptphone || 'No contact details'}
                    </span>
                  </span>
                  <span className="shrink-0 font-mono text-xs tabular-nums">
                    {patient.id}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}

      <div className="flex flex-wrap items-center justify-end gap-3">
        <Button
          disabled={!selected}
          isLoading={isBusy}
          onClick={() => selected && onSelect(selected)}
        >
          {selected ? `Continue with ${patientName(selected)}` : 'Select a patient'}
        </Button>
      </div>
    </Card>
  )
}
