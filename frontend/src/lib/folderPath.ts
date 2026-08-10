export function folderPathFromFiles(files: File[]): string {
  const first = files[0]
  if (!first) return ''

  const relative = first.webkitRelativePath
  if (relative) return relative.split('/')[0] ?? ''

  return files.length === 1 ? first.name : ''
}
