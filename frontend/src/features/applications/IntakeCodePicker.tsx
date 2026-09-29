import { Check, UserPlus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { TextField } from '@/components/ui/Field'
import { Badge, Card } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import { useIntakeCodes } from '@/hooks/useResources'
import type { AvailableCode } from '@/schemas/intake'

/**
 * Step one: which patient's de-identified documents is this application for?
 *
 * Only codes with redacted files nobody has attached yet are offered. The
 * code is shown large on purpose -- a typo upstream (AA1235 for AA1234) is
 * still a valid code, and this is the first place a person can notice.
 */
export function IntakeCodePicker({
  value,
  onChoose,
  disabled = false,
}: {
  value: string | undefined
  onChoose: (code: AvailableCode) => void
  disabled?: boolean
}) {
  const codes = useIntakeCodes()
  const [search, setSearch] = useState('')

  const visible = useMemo(() => {
    const term = search.trim().toUpperCase()
    const rows = codes.data ?? []
    return term ? rows.filter((row) => row.code.includes(term)) : rows
  }, [codes.data, search])

  return (
    <Card className="p-5">
      <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
        Patient code
      </h2>
      <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
        Codes with de-identified documents waiting in the intake folder. Check
        the code against what you expect -- a mistyped code upstream still
        looks like a real one.
      </p>

      <div className="mt-4 max-w-xs">
        <TextField
          label="Find a code"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="AA1234"
          aria-label="Find a patient code"
          disabled={disabled}
        />
      </div>

      {codes.isLoading ? (
        <div className="mt-4">
          <Spinner size="md" label="Loading codes" />
        </div>
      ) : visible.length === 0 ? (
        <p className="mt-4 text-sm text-[rgb(var(--foreground-muted))]">
          {search
            ? 'No code matches.'
            : 'Nothing is waiting. Documents appear here once the intake sweep has de-identified them.'}
        </p>
      ) : (
        <ul className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3" role="listbox">
          {visible.map((row) => {
            const chosen = row.code === value
            return (
              <li key={row.code}>
                <button
                  type="button"
                  role="option"
                  aria-selected={chosen}
                  disabled={disabled}
                  onClick={() => onChoose(row)}
                  className={
                    'w-full rounded-lg border p-3 text-left transition-colors disabled:opacity-50 ' +
                    (chosen
                      ? 'border-[rgb(var(--primary))] bg-[rgb(var(--background-secondary))]'
                      : 'border-[rgb(var(--border))] hover:border-[rgb(var(--foreground-muted))]')
                  }
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="font-mono text-lg font-bold tracking-wide">
                      {row.code}
                    </span>
                    {chosen ? <Check className="size-4" aria-hidden="true" /> : null}
                  </span>
                  <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[rgb(var(--foreground-muted))]">
                    {row.files} document{row.files === 1 ? '' : 's'}
                    {row.patient_exists ? (
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
                    title={row.folder}
                  >
                    {row.folder}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
