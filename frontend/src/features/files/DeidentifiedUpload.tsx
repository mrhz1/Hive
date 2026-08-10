import { Upload } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { SelectField } from '@/components/ui/Field'
import { Card } from '@/components/ui/Misc'
import { patientHooks, useUploadDeidentifiedFile } from '@/hooks/useResources'
import { cn } from '@/lib/cn'
import { patientName } from '@/schemas/patient'
import type { DeidentifiedFile } from '@/schemas/deidentifiedFile'

type Mode = 'new' | 'replace'

export function DeidentifiedUpload({ files }: { files: DeidentifiedFile[] }) {
  const { data: patients } = patientHooks.useList()
  const upload = useUploadDeidentifiedFile()
  const inputRef = useRef<HTMLInputElement>(null)

  const [patientId, setPatientId] = useState('')
  const [mode, setMode] = useState<Mode>('new')
  const [replacesFileId, setReplacesFileId] = useState('')
  const [file, setFile] = useState<File | null>(null)

  const patientOptions = useMemo(
    () =>
      (patients ?? []).map((patient) => ({
        value: patient.id,
        label: `${patientName(patient)} (${patient.id})`,
      })),
    [patients]
  )

  const replaceable = useMemo(
    () => files.filter((candidate) => candidate.patient_id === patientId),
    [files, patientId]
  )

  const ready =
    Boolean(patientId) &&
    Boolean(file) &&
    (mode === 'new' || Boolean(replacesFileId))

  function reset() {
    setFile(null)
    setReplacesFileId('')
    if (inputRef.current) inputRef.current.value = ''
  }

  async function submit() {
    if (!file || !patientId) return
    try {
      await upload.mutateAsync({
        patientId,
        file,
        ...(mode === 'replace' && replacesFileId
          ? { replacesFileId }
          : {}),
      })
      reset()
    } catch {
      // The hook toasts its own message.
    }
  }

  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className="text-sm font-bold">Upload a de-identified file</h2>
        <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
          For documents redacted by hand, when the automatic pass missed
          something.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField
          label="Patient"
          required
          value={patientId}
          onChange={(event) => {
            setPatientId(event.target.value)
            // The replace target belongs to the old patient.
            setReplacesFileId('')
          }}
          options={patientOptions}
          placeholder="Choose a patient"
          placeholderDisabled
        />

        <fieldset className="flex flex-col justify-end gap-2">
          <legend className="mb-1 text-sm font-medium">This file is</legend>
          <div className="flex gap-2">
            {(
              [
                { value: 'new', label: 'A new file' },
                { value: 'replace', label: 'Replacing an existing one' },
              ] as const
            ).map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={mode === option.value}
                onClick={() => setMode(option.value)}
                className={cn(
                  'flex-1 rounded-lg border px-3 py-2 text-xs font-semibold transition-colors',
                  mode === option.value
                    ? 'border-[rgb(var(--primary))] bg-[rgb(var(--primary))]/5 ring-1 ring-[rgb(var(--primary))]'
                    : 'border-[rgb(var(--border))] bg-[rgb(var(--surface))]'
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </fieldset>
      </div>

      {mode === 'replace' ? (
        <SelectField
          label="File to replace"
          required
          value={replacesFileId}
          onChange={(event) => setReplacesFileId(event.target.value)}
          options={replaceable.map((candidate) => ({
            value: candidate.id,
            label: candidate.name,
          }))}
          placeholder={
            patientId
              ? replaceable.length
                ? 'Choose the file to replace'
                : 'This patient has no de-identified files yet'
              : 'Choose a patient first'
          }
          placeholderDisabled
          disabled={!patientId || replaceable.length === 0}
          hint="The row keeps its id; only the redacted copy changes."
        />
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.dcm,.dicom,.doc,.docx"
          aria-label="De-identified file"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          className="text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-[rgb(var(--surface-muted))] file:px-3 file:py-2 file:text-sm"
        />
        <Button
          disabled={!ready}
          isLoading={upload.isPending}
          leadingIcon={<Upload className="size-3.5" aria-hidden="true" />}
          onClick={() => void submit()}
        >
          {mode === 'replace' ? 'Replace file' : 'Upload file'}
        </Button>
      </div>
    </Card>
  )
}
