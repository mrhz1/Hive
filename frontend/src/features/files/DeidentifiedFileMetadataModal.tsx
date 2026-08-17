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
      // This library only ever holds redacted copies, so the metadata
      // worth reading here is theirs -- not the original's, which is
      // what the row is a redaction of.
      deidentified
      onClose={onClose}
    />
  )
}
