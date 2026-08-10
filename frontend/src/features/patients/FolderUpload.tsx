import { Upload } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Misc'
import { FilePicker } from './FilePicker'

export function FolderUpload({
  onUpload,
  isUploading,
}: {
  onUpload: (files: File[], description?: string) => Promise<unknown>
  isUploading: boolean
}) {
  const [selected, setSelected] = useState<File[]>([])
  const [description, setDescription] = useState('')

  return (
    <Card className="p-5">
      <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
        Upload documents
      </h2>

      <div className="mt-4">
        <FilePicker
          files={selected}
          onFilesChange={setSelected}
          disabled={isUploading}
          label=""
        />
      </div>

      {selected.length > 0 ? (
        <div className="mt-3 space-y-3">
          <input
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Description (optional, applied to all)"
            disabled={isUploading}
            className="w-full rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--input-bg))] px-4 py-2.5 text-sm text-[rgb(var(--input-text))] transition-all outline-none focus:border-[rgb(var(--input-ring))] focus:ring-4 focus:ring-[rgb(var(--input-ring))]/15"
          />

          <Button
            isLoading={isUploading}
            leadingIcon={<Upload className="size-4" aria-hidden="true" />}
            onClick={async () => {
              await onUpload(selected, description.trim() || undefined)
              setSelected([])
              setDescription('')
            }}
          >
            {isUploading
              ? 'Uploading…'
              : `Upload ${selected.length} file${selected.length === 1 ? '' : 's'}`}
          </Button>
        </div>
      ) : null}
    </Card>
  )
}
