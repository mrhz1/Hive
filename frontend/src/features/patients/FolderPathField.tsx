import { FolderUp, X } from 'lucide-react'
import { useRef } from 'react'
import { Button } from '@/components/ui/Button'
import { folderPathFromFiles } from '@/lib/folderPath'
import { formatFileSize } from '@/schemas/applicationFile'

export function FolderPathField({
  label,
  value,
  files,
  onSelect,
  required = false,
  disabled = false,
  error,
  hint,
}: {
  label: string
  value: string
  files: File[]
  /** '' for path means "nothing derivable" -- keep the current value. */
  onSelect: (path: string, files: File[]) => void
  required?: boolean
  disabled?: boolean
  error?: string
  hint?: string
}) {
  const inputRef = useRef<HTMLInputElement>(null)

  function openPicker(directory: boolean) {
    const input = inputRef.current
    if (!input) return

    if (directory) {
      input.setAttribute('webkitdirectory', '')
      input.setAttribute('directory', '')
    } else {
      input.removeAttribute('webkitdirectory')
      input.removeAttribute('directory')
    }
    // Reset so re-picking the same folder still fires a change event.
    input.value = ''
    input.click()
  }

  const totalBytes = files.reduce((sum, file) => sum + file.size, 0)

  return (
    <div className="w-full space-y-2">
      <span className="ml-0.5 block text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
        {label}
        {required ? <span className="ml-1 text-[rgb(var(--danger))]">*</span> : null}
      </span>

      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        aria-label={`${label} input`}
        onChange={(event) => {
          const picked = Array.from(event.target.files ?? [])
          onSelect(folderPathFromFiles(picked), picked)
        }}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          onClick={() => openPicker(true)}
          disabled={disabled}
          leadingIcon={<FolderUp className="size-4" aria-hidden="true" />}
        >
          Choose folder
        </Button>
        <Button variant="ghost" onClick={() => openPicker(false)} disabled={disabled}>
          Choose files
        </Button>
        {value || files.length > 0 ? (
          <Button
            variant="ghost"
            onClick={() => onSelect('', [])}
            disabled={disabled}
            leadingIcon={<X className="size-3.5" aria-hidden="true" />}
          >
            Clear
          </Button>
        ) : null}
      </div>

      {value ? (
        <p className="truncate rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] px-3 py-2 font-mono text-xs">
          {value}
        </p>
      ) : null}

      {files.length > 0 ? (
        <>
          <p className="px-1 text-xs font-semibold">
            {files.length} file{files.length === 1 ? '' : 's'} selected
            <span className="ml-2 font-normal text-[rgb(var(--foreground-muted))]">
              {formatFileSize(totalBytes)}
            </span>
          </p>
          <ul className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] p-3">
            {files.map((file) => (
              <li
                key={file.webkitRelativePath || file.name}
                className="flex items-center justify-between gap-3 text-xs"
              >
                <span className="truncate">{file.webkitRelativePath || file.name}</span>
                <span className="shrink-0 text-[rgb(var(--foreground-muted))] tabular-nums">
                  {formatFileSize(file.size)}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {error ? (
        <p className="px-1 text-xs font-medium text-[rgb(var(--danger))]">{error}</p>
      ) : hint ? (
        <p className="px-1 text-[11px] text-[rgb(var(--foreground-muted))]">{hint}</p>
      ) : null}
    </div>
  )
}
