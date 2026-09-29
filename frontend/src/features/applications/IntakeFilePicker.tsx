import { Paperclip } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge, Card } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import {
  useAttachIntakeFiles,
  useAvailableIntakeFiles,
} from '@/hooks/useResources'
import { formatFileSize } from '@/schemas/applicationFile'
import { byFolder } from '@/schemas/intake'

/**
 * Step two: take this patient's de-identified documents from intake.
 *
 * A whole folder or single files. Only the redacted copies are offered --
 * that is what was checked -- and attaching brings the original along on
 * the same row, so both stay one click apart for review.
 */
export function IntakeFilePicker({
  applicationId,
  code,
}: {
  applicationId: string
  code: string
}) {
  const available = useAvailableIntakeFiles(code)
  const attach = useAttachIntakeFiles(applicationId)
  const [chosen, setChosen] = useState<Set<string>>(new Set())

  const groups = useMemo(() => byFolder(available.data ?? []), [available.data])

  function toggle(ids: string[], on: boolean) {
    setChosen((current) => {
      const next = new Set(current)
      for (const id of ids) {
        if (on) next.add(id)
        else next.delete(id)
      }
      return next
    })
  }

  async function submit() {
    try {
      await attach.mutateAsync([...chosen])
      setChosen(new Set())
    } catch {
      // Toasted by the hook.
    }
  }

  const total = available.data?.length ?? 0

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
            De-identified documents for{' '}
            <span className="font-mono text-sm text-[rgb(var(--foreground))]">{code}</span>
          </h2>
          <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
            From the intake folder. Take a whole folder or single files; each
            one's original comes with it.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={total === 0 || attach.isPending}
            onClick={() =>
              toggle(
                (available.data ?? []).map((f) => f.id),
                chosen.size !== total
              )
            }
          >
            {chosen.size === total && total > 0 ? 'Clear' : 'Select all'}
          </Button>
          <Button
            size="sm"
            disabled={chosen.size === 0}
            isLoading={attach.isPending}
            leadingIcon={<Paperclip className="size-3.5" aria-hidden="true" />}
            onClick={() => void submit()}
          >
            Attach {chosen.size || ''}
          </Button>
        </div>
      </div>

      {available.isLoading ? (
        <div className="mt-4">
          <Spinner size="md" label="Loading documents" />
        </div>
      ) : total === 0 ? (
        <p className="mt-4 text-sm text-[rgb(var(--foreground-muted))]">
          Nothing left to attach for {code}. Everything de-identified under
          this code is already on an application.
        </p>
      ) : (
        <div className="mt-4 space-y-4">
          {groups.map(([folder, files]) => {
            const ids = files.map((f) => f.id)
            const all = ids.every((id) => chosen.has(id))
            const some = !all && ids.some((id) => chosen.has(id))
            return (
              <fieldset
                key={folder}
                className="rounded-lg border border-[rgb(var(--border))]"
              >
                <legend className="sr-only">{folder}</legend>
                <label className="flex cursor-pointer items-center gap-3 border-b border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] px-3 py-2">
                  <input
                    type="checkbox"
                    checked={all}
                    ref={(el) => {
                      if (el) el.indeterminate = some
                    }}
                    onChange={(event) => toggle(ids, event.target.checked)}
                    aria-label={`Select the whole folder ${folder}`}
                  />
                  <span className="font-mono text-sm font-semibold">{folder}/</span>
                  <Badge tone="neutral">
                    {files.length} file{files.length === 1 ? '' : 's'}
                  </Badge>
                </label>
                <ul>
                  {files.map((file) => (
                    <li key={file.id}>
                      <label className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-[rgb(var(--background-secondary))]">
                        <input
                          type="checkbox"
                          checked={chosen.has(file.id)}
                          onChange={(event) => toggle([file.id], event.target.checked)}
                          aria-label={`Select ${file.output_name ?? file.file_name}`}
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-mono text-sm">
                            {file.output_name}
                          </span>
                          <span className="block truncate text-xs text-[rgb(var(--foreground-muted))]">
                            from {file.file_name} · {formatFileSize(file.file_size)}
                          </span>
                        </span>
                        <Badge tone="neutral">{file.file_extension}</Badge>
                      </label>
                    </li>
                  ))}
                </ul>
              </fieldset>
            )
          })}
        </div>
      )}
    </Card>
  )
}
