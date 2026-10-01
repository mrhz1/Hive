import { Check, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { TextField } from '@/components/ui/Field'
import { Badge, Card } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import { useIntakeCodes } from '@/hooks/useResources'
import type { AvailableCode } from '@/schemas/intake'

const MAX_ROWS = 200

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
          : 'Nothing is waiting. Documents appear here once the De-Identifier has processed them.'}
      </p>
    )
  } else {
    const shown = codes.slice(0, MAX_ROWS)
    content = (
      <>
        <ul
          className="mt-4 max-h-96 divide-y divide-[rgb(var(--border))] overflow-y-auto rounded-lg border border-[rgb(var(--border))]"
          role="listbox"
          aria-label="Patient codes"
        >
          {shown.map((item) => {
            const selected = item.code === value
            const rowClass = selected
              ? 'bg-[rgb(var(--background-secondary))]'
              : 'hover:bg-[rgb(var(--background-secondary))]'

            return (
              <li key={item.code}>
                <button
                  type="button"
                  role="option"
                  aria-selected={selected}
                  disabled={disabled}
                  onClick={() => onChoose(item)}
                  className={`flex w-full items-center gap-3 px-3 py-2 text-left text-sm transition-colors disabled:opacity-50 ${rowClass}`}
                >
                  <span className="flex w-4 shrink-0 justify-center">
                    {selected && (
                      <Check
                        className="size-4 text-[rgb(var(--primary))]"
                        aria-hidden="true"
                      />
                    )}
                  </span>
                  <span className="w-24 shrink-0 font-mono font-bold tracking-wide">
                    {item.code}
                  </span>
                  <span className="w-24 shrink-0 text-xs text-[rgb(var(--foreground-muted))]">
                    {item.files} {item.files === 1 ? 'document' : 'documents'}
                  </span>
                  <span className="w-32 shrink-0">
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
                    className="hidden min-w-0 flex-1 truncate font-mono text-[11px] text-[rgb(var(--foreground-muted))] sm:block"
                    title={item.folder}
                  >
                    {item.folder}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
        <p className="mt-2 text-xs text-[rgb(var(--foreground-muted))]">
          {codes.length > MAX_ROWS
            ? `Showing ${MAX_ROWS} of ${codes.length} codes. Type to narrow the list.`
            : `${codes.length} ${codes.length === 1 ? 'code' : 'codes'}`}
        </p>
      </>
    )
  }

  return (
    <Card className="p-5">
      <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
        Patient code
      </h2>
      <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
        Codes with de-identified documents from the De-Identifier that are not on an
        application yet. Make sure the code is the one you expect, a typo upstream can
        still look like a real code.
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
