import { FolderUp, X } from 'lucide-react'
import { useRef } from 'react'
import { Button } from '@/components/ui/Button'
import { formatFileSize } from '@/schemas/patientFile'

/**
 * Controlled folder/file selection.
 *
 * `webkitdirectory` is the only way a browser can offer a folder chooser;
 * despite the vendor prefix it is supported across current Chrome, Edge,
 * Firefox and Safari. It is not in React's DOM typings, hence the ref +
 * setAttribute rather than a JSX prop.
 *
 * Selection is shown for confirmation before anything is sent: picking a
 * folder can pull in far more than expected, and there is no undo once
 * the files are stored.
 */
export function FilePicker({
  files,
  onFilesChange,
  disabled = false,
  label = 'Files',
  hint = 'Choose a folder to include everything inside it, or pick individual files.',
}: {
  files: File[]
  onFilesChange: (files: File[]) => void
  disabled?: boolean
  label?: string
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
      </span>

      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        aria-label="File input"
        onChange={(event) => onFilesChange(Array.from(event.target.files ?? []))}
      />

      <div className="flex flex-wrap gap-2">
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
        {files.length > 0 ? (
          <Button
            variant="ghost"
            onClick={() => onFilesChange([])}
            disabled={disabled}
            leadingIcon={<X className="size-3.5" aria-hidden="true" />}
          >
            Clear
          </Button>
        ) : null}
      </div>

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
      ) : (
        <p className="px-1 text-[11px] text-[rgb(var(--foreground-muted))]">{hint}</p>
      )}
    </div>
  )
}
