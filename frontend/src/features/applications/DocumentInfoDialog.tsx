import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { CheckboxField, SelectField, TextField } from '@/components/ui/Field'
import {
  MODALITY_OPTIONS,
  UNKNOWN,
  isoDocumentDate,
  type ApplicationFile,
} from '@/schemas/applicationFile'

/** Set the modality and date a redacted file is named by. */
export function DocumentInfoDialog({
  file,
  isBusy,
  onConfirm,
  onCancel,
}: {
  file: ApplicationFile
  isBusy?: boolean
  onConfirm: (modality: string, documentDate: string) => void
  onCancel: () => void
}) {
  const known = isoDocumentDate(file.document_date)
  const [modality, setModality] = useState(file.modality || UNKNOWN)
  const [day, setDay] = useState(known ?? '')
  const [dateUnknown, setDateUnknown] = useState(!known)
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onCancel])

  const dateError =
    touched && !dateUnknown && !day ? 'Pick a date or tick "Date unknown"' : undefined

  function confirm() {
    setTouched(true)
    if (!dateUnknown && !day) return
    onConfirm(modality, dateUnknown ? UNKNOWN : day)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgb(var(--background))]/80 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={`Modality and date of ${file.original_file_name}`}
    >
      <div className="w-full max-w-lg space-y-4 rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-5 shadow-xl">
        <div>
          <h2 className="text-sm font-bold">Modality and date</h2>
          <p className="mt-1 text-xs break-all text-[rgb(var(--foreground-muted))]">
            The de-identified copy is renamed to match:{' '}
            {file.deidentified_file_name ?? file.original_file_name}
          </p>
        </div>

        <SelectField
          label="Modality"
          value={modality}
          options={MODALITY_OPTIONS}
          onChange={(event) => setModality(event.target.value)}
        />

        <TextField
          label="Document date"
          type="date"
          value={day}
          disabled={dateUnknown}
          error={dateError}
          onChange={(event) => setDay(event.target.value)}
        />
        <CheckboxField
          label="Date unknown"
          checked={dateUnknown}
          onChange={(event) => setDateUnknown(event.target.checked)}
        />

        <div className="flex flex-wrap justify-end gap-3">
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button isLoading={isBusy} onClick={confirm}>
            Save
          </Button>
        </div>
      </div>
    </div>
  )
}
