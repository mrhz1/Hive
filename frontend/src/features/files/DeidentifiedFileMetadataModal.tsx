import { FileMetadataModal } from '@/features/applications/FileMetadataModal'
import type { DeidentifiedFile } from '@/schemas/deidentifiedFile'

export function DeidentifiedFileMetadataModal({
  file,
  onClose,
}: {
  file: DeidentifiedFile
  onClose: () => void
}) {
  return (
    <FileMetadataModal
      file={{ id: file.id, original_file_name: file.name }}
      onClose={onClose}
    />
  )
}
