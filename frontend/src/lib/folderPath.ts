/**
 * Derives the stored path from a browser file selection.
 *
 * `webkitRelativePath` is 'chosen-folder/sub/file.pdf' for a folder pick,
 * so its first segment is the folder the user actually chose. A plain
 * multi-file pick has no folder at all -- there is no honest path to
 * derive from unrelated files, so this returns '' and the caller keeps
 * whatever was already there rather than overwriting a good value with a
 * guess.
 *
 * Lives here rather than beside FolderPathField so that component file
 * exports only components.
 */
export function folderPathFromFiles(files: File[]): string {
  const first = files[0]
  if (!first) return ''

  const relative = first.webkitRelativePath
  if (relative) return relative.split('/')[0] ?? ''

  return files.length === 1 ? first.name : ''
}
