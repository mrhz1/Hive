import { Check, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { TextField } from '@/components/ui/Field'
import { Badge, Card } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import { useIntakeCodes } from '@/hooks/useResources'
import type { AvailableCode } from '@/schemas/intake'

type Props = {
  value: string | undefined
  onChoose: (code: AvailableCode) => void
  disabled?: boolean
}

export function IntakeCodePicker({ value, onChoose, disabled = false }: Props) {
  const { data, isLoading } = useIntakeCodes()
  const [search, setSearch] = useState('')

  const allCodes = data ?? []
  const searchText = search.trim().toUpperCase()
  const codes = searchText
    ? allCodes.filter((c) => c.code.includes(searchText))
    : allCodes

  let content
  if (isLoading) {
    content = (
      <div className="mt-4">
        <Spinner size="md" label="Loading codes" />
      </div>
    )
  } else if (codes.length === 0) {
    content = (
      <p className="mt-4 text-sm text-[rgb(var(--foreground-muted))]">
        {search
          ? 'No code matches.'
          : 'Nothing is waiting. Documents appear here once the intake sweep has de-identified them.'}
      </p>
    )
  } else {
    content = (
      <ul className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3" role="listbox">
        {codes.map((item) => {
          const selected = item.code === value
          const borderClass = selected
            ? 'border-[rgb(var(--primary))] bg-[rgb(var(--background-secondary))]'
            : 'border-[rgb(var(--border))] hover:border-[rgb(var(--foreground-muted))]'

          return (
            <li key={item.code}>
              <button
                type="button"
                role="option"
                aria-selected={selected}
                disabled={disabled}
                onClick={() => onChoose(item)}
                className={`w-full rounded-lg border p-3 text-left transition-colors disabled:opacity-50 ${borderClass}`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="font-mono text-lg font-bold tracking-wide">
                    {item.code}
                  </span>
                  {selected && <Check className="size-4" aria-hidden="true" />}
                </span>
                <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[rgb(var(--foreground-muted))]">
                  {item.files} {item.files === 1 ? 'document' : 'documents'}
                  {item.patient_exists ? (
                    <Badge tone="neutral">existing patient</Badge>
                  ) : (
                    <Badge tone="info">
                      <UserPlus className="mr-1 inline size-3" aria-hidden="true" />
                      new patient
                    </Badge>
                  )}
                </span>
                <span
                  className="mt-1 block truncate font-mono text-[11px] text-[rgb(var(--foreground-muted))]"
                  title={item.folder}
                >
                  {item.folder}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    )
  }

  return (
    <Card className="p-5">
      <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
        Patient code
      </h2>
      <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
        Codes with de-identified documents waiting in the intake folder. Make sure the
        code is the one you expect, a typo upstream can still look like a real code.
      </p>

      <div className="mt-4 max-w-xs">
        <TextField
          label="Find a code"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="AA1234"
          aria-label="Find a patient code"
          disabled={disabled}
        />
      </div>

      {content}
    </Card>
  )
}
