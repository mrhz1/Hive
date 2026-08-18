import { FolderUp, X } from 'lucide-react'
import { useRef } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { partitionBySupport, SUPPORTED_FORMATS_LABEL } from '@/lib/fileType'
import { folderPathFromFiles } from '@/lib/folderPath'
import { formatFileSize } from '@/schemas/applicationFile'

export function FolderPathField({
  label,
  value,
  files,
  onSelect,
  onPathChange,
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
  /**
   * The path, typed rather than picked. Separate from onSelect because
   * an empty string means opposite things in the two cases: the picker
   * yielding nothing must not wipe the path, but somebody clearing the
   * box by hand must.
   */
  onPathChange?: (path: string) => void
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

  async function handlePicked(input: HTMLInputElement) {
    const picked = Array.from(input.files ?? [])
    if (picked.length === 0) return

    // Set by openPicker just before the dialog opened, and still there
    // now: which button was clicked, not a guess from the result.
    const isDirectory = input.hasAttribute('webkitdirectory')
    const { supported, unsupported } = await partitionBySupport(picked)

    // The path comes from the full, unfiltered pick -- the folder was
    // still the folder the user chose, even if nothing supported turned
    // up in it, and typing that name back in by hand is the annoyance
    // this field exists to avoid.
    const path = folderPathFromFiles(picked)

    if (isDirectory) {
      // A folder can hold anything; only DICOM, PDF and Word belong in
      // the batch, and flagging every unrelated file in it would be
      // noise, not help.
      if (unsupported.length > 0 && supported.length > 0) {
        toast.warning(
          `Skipped ${unsupported.length} unsupported file${unsupported.length === 1 ? '' : 's'} -- only ${SUPPORTED_FORMATS_LABEL} documents are uploaded.`
        )
      } else if (unsupported.length > 0) {
        toast.error(
          `No supported files found in that folder -- only ${SUPPORTED_FORMATS_LABEL} documents are uploaded.`
        )
      }
      onSelect(path, supported)
      return
    }

    // Chosen by hand, not swept in with a folder: a file that does not
    // belong here is a mistake worth stopping on, not skipping past.
    if (unsupported.length > 0) {
      const names = unsupported.map((file) => file.name)
      toast.error(
        names.length === 1
          ? `"${names[0]}" is not a supported file type. Only ${SUPPORTED_FORMATS_LABEL} documents are accepted.`
          : `${names.length} files are not supported and were not added (only ${SUPPORTED_FORMATS_LABEL} documents are accepted): ${names.join(', ')}`
      )
    }
    onSelect(path, supported)
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
        onChange={(event) => void handlePicked(event.target)}
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

      {/* Editable, because a browser will not tell us where the folder
          it just handed over actually lives -- webkitRelativePath is the
          folder's *name* and nothing above it. So the picker fills in
          'samples' and whoever knows the rest can paste the full path
          over it, which is what makes it findable by anyone reading it
          later. */}
      <input
        type="text"
        value={value}
        disabled={disabled}
        onChange={(event) => onPathChange?.(event.target.value)}
        readOnly={!onPathChange}
        placeholder="/data/intake/samples or \\\\server\\share\\samples"
        aria-label={`${label} path`}
        className="w-full truncate rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] px-3 py-2 font-mono text-xs focus:border-[rgb(var(--primary))] focus:ring-1 focus:ring-[rgb(var(--primary))] focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
      />

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
