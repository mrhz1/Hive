import { ShieldCheck } from 'lucide-react'
import { useRef, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Misc'
import { useUploadDeidentifiedApplicationFile } from '@/hooks/useResources'

/**
 * Attach a document that is already redacted.
 *
 * For work done outside the pipeline -- redacted by hand, or arriving
 * from elsewhere already clean. It goes straight in as finished: there
 * is no original behind it and nothing left to run over it, so it is
 * marked done and redacted, and named exactly as an automatic output
 * would have been.
 */
export function DeidentifiedAttach({ applicationId }: { applicationId: string }) {
  const upload = useUploadDeidentifiedApplicationFile(applicationId)
  const inputRef = useRef<HTMLInputElement>(null)

  const [file, setFile] = useState<File | null>(null)
  const [description, setDescription] = useState('')

  async function submit() {
    if (!file) return
    try {
      await upload.mutateAsync({
        file,
        ...(description.trim() ? { description: description.trim() } : {}),
      })
      setFile(null)
      setDescription('')
      if (inputRef.current) inputRef.current.value = ''
    } catch {
      // The hook toasts its own message.
    }
  }

  return (
    <Card className="p-5">
      <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
        Attach a de-identified document
      </h2>
      <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
        Already redacted, with no original to keep here. It is filed as
        done and named like the pipeline's own output. PDF, DICOM or Word.
      </p>

      <div className="mt-4 space-y-3">
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.dcm,.dicom,.doc,.docx"
          aria-label="De-identified document"
          disabled={upload.isPending}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          className="text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-[rgb(var(--surface-muted))] file:px-3 file:py-2 file:text-sm"
        />

        {file ? (
          <div className="space-y-3">
            <input
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Description (optional)"
              disabled={upload.isPending}
              className="w-full rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--input-bg))] px-4 py-2.5 text-sm text-[rgb(var(--input-text))] transition-all outline-none focus:border-[rgb(var(--input-ring))] focus:ring-4 focus:ring-[rgb(var(--input-ring))]/15"
            />
            <Button
              isLoading={upload.isPending}
              leadingIcon={<ShieldCheck className="size-4" aria-hidden="true" />}
              onClick={() => void submit()}
            >
              Attach {file.name}
            </Button>
          </div>
        ) : null}
      </div>
    </Card>
  )
}
