import { Paperclip } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Badge, Card } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import { useAttachIntakeFiles, useCodeFiles } from '@/hooks/useResources'
import { formatFileSize } from '@/schemas/applicationFile'
import { groupByFolder } from '@/schemas/intake'

type Props = {
  applicationId: string
  code: string
}

export function IntakeFilePicker({ applicationId, code }: Props) {
  const available = useCodeFiles(code)
  const attach = useAttachIntakeFiles(applicationId)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const files = available.data ?? []
  const total = files.length
  const groups = groupByFolder(files)
  const allSelected = total > 0 && selected.size === total

  function setChecked(ids: string[], checked: boolean) {
    setSelected((current) => {
      const next = new Set(current)
      for (const id of ids) {
        if (checked) next.add(id)
        else next.delete(id)
      }
      return next
    })
  }

  async function attachSelected() {
    try {
      await attach.mutateAsync([...selected])
      setSelected(new Set())
    } catch {
      // error toast comes from the hook
    }
  }

  let content
  if (available.isLoading) {
    content = (
      <div className="mt-4">
        <Spinner size="md" label="Loading documents" />
      </div>
    )
  } else if (total === 0) {
    content = (
      <p className="mt-4 text-sm text-[rgb(var(--foreground-muted))]">
        Nothing left to attach for {code}. Everything de-identified under this code is
        already on an application.
      </p>
    )
  } else {
    content = (
      <div className="mt-4 space-y-4">
        {groups.map(([folder, folderFiles]) => {
          const ids = folderFiles.map((f) => f.id)
          const checkedCount = ids.filter((id) => selected.has(id)).length
          const allChecked = checkedCount === ids.length
          const someChecked = checkedCount > 0 && !allChecked

          return (
            <fieldset
              key={folder}
              className="rounded-lg border border-[rgb(var(--border))]"
            >
              <legend className="sr-only">{folder}</legend>
              <label className="flex cursor-pointer items-center gap-3 border-b border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] px-3 py-2">
                <input
                  type="checkbox"
                  checked={allChecked}
                  ref={(el) => {
                    if (el) el.indeterminate = someChecked
                  }}
                  onChange={(e) => setChecked(ids, e.target.checked)}
                  aria-label={`Select the whole folder ${folder}`}
                />
                <span className="font-mono text-sm font-semibold">{folder}/</span>
                <Badge tone="neutral">
                  {folderFiles.length} {folderFiles.length === 1 ? 'file' : 'files'}
                </Badge>
              </label>
              <ul>
                {folderFiles.map((file) => (
                  <li key={file.id}>
                    <label className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-[rgb(var(--background-secondary))]">
                      <input
                        type="checkbox"
                        checked={selected.has(file.id)}
                        onChange={(e) => setChecked([file.id], e.target.checked)}
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
    )
  }

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
            De-identified documents for{' '}
            <span className="font-mono text-sm text-[rgb(var(--foreground))]">
              {code}
            </span>
          </h2>
          <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
            From the intake folder. Take a whole folder or single files; each one's
            original comes with it.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={total === 0 || attach.isPending}
            onClick={() =>
              setChecked(
                files.map((f) => f.id),
                !allSelected
              )
            }
          >
            {allSelected ? 'Clear' : 'Select all'}
          </Button>
          <Button
            size="sm"
            disabled={selected.size === 0}
            isLoading={attach.isPending}
            leadingIcon={<Paperclip className="size-3.5" aria-hidden="true" />}
            onClick={() => void attachSelected()}
          >
            Attach {selected.size || ''}
          </Button>
        </div>
      </div>

      {content}
    </Card>
  )
}
