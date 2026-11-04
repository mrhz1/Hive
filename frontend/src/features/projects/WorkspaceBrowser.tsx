import { ChevronLeft, ChevronRight, Eye, FileText, Image, Sheet } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { DataTable, type Column } from '@/components/DataTable'
import { Button } from '@/components/ui/Button'
import { SelectField, TextField } from '@/components/ui/Field'
import { Badge } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { PdfViewer } from '@/features/patients/PdfViewer'
import { useWorkspaceFiles, useWorkspaceTable } from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'
import { projectsApi } from '@/lib/api/resources'
import type { ProjectDetail, WorkspaceFile } from '@/schemas/project'

const mutedClass = 'text-xs text-[rgb(var(--foreground-muted))]'
const PAGE_SIZE = 50

type Opened =
  | { file: WorkspaceFile; kind: 'table' }
  | { file: WorkspaceFile; kind: 'pdf' | 'image'; url: string; frames?: number }
  | { file: WorkspaceFile; kind: 'text'; text: string; truncated: boolean }

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const KIND_LABEL: Record<WorkspaceFile['kind'], string> = {
  table: 'table',
  pdf: 'pdf',
  image: 'image',
  dicom: 'dicom',
  text: 'text',
  other: 'no preview',
}

/** Read-only browser of a project's Zone 1X workspace (protocol 9.2). */
export function WorkspaceBrowser({ project }: { project: ProjectDetail }) {
  const files = useWorkspaceFiles(project.id)
  const [openingPath, setOpeningPath] = useState<string | null>(null)
  const [opened, setOpened] = useState<Opened | null>(null)
  const [filter, setFilter] = useState('')

  const all = files.data ?? []
  const needle = filter.trim().toLowerCase()
  const shown = needle ? all.filter((f) => f.path.toLowerCase().includes(needle)) : all

  async function open(file: WorkspaceFile) {
    if (file.kind === 'table') {
      setOpened({ file, kind: 'table' })
      return
    }
    setOpeningPath(file.path)
    try {
      if (file.kind === 'dicom') {
        const image = await projectsApi.workspaceImage(project.id, file.path)
        setOpened({ file, kind: 'image', url: image.url, frames: image.frames })
      } else if (file.kind === 'text') {
        const text = await projectsApi.workspaceText(project.id, file.path)
        setOpened({ file, kind: 'text', text: text.text, truncated: text.truncated })
      } else {
        const blob = await projectsApi.workspaceContent(project.id, file.path)
        setOpened({
          file,
          kind: file.kind === 'pdf' ? 'pdf' : 'image',
          url: URL.createObjectURL(blob),
        })
      }
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Could not open the file')
    } finally {
      setOpeningPath(null)
    }
  }

  function close() {
    if (opened && 'url' in opened) URL.revokeObjectURL(opened.url)
    setOpened(null)
  }

  const columns: Array<Column<WorkspaceFile>> = [
    {
      id: 'path',
      header: 'File',
      cell: (f) => <span className="font-mono text-xs break-all">{f.path}</span>,
      sortValue: (f) => f.path,
    },
    {
      id: 'kind',
      header: 'Type',
      cell: (f) => (
        <Badge tone={f.kind === 'other' ? 'neutral' : 'info'}>{KIND_LABEL[f.kind]}</Badge>
      ),
      sortValue: (f) => f.kind,
    },
    {
      id: 'size',
      header: 'Size',
      cell: (f) => <span className="text-sm">{formatSize(f.size)}</span>,
      sortValue: (f) => f.size,
      isNumeric: true,
    },
  ]

  return (
    <div className="mt-5 space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="max-w-2xl">
          <h3 className="text-sm font-semibold">Workspace files</h3>
          <p className={`mt-1 ${mutedClass}`}>
            Preview only. Every file you open is recorded in the access log. Corrections
            go to the source (e.g. REDCap) or the cleaning scripts, never to a copy in
            Excel (protocol 9.2.3).
          </p>
        </div>
        <div className="w-64">
          <TextField
            label="Find a file"
            value={filter}
            placeholder="e.g. patients, AA050"
            onChange={(event) => setFilter(event.target.value)}
          />
        </div>
      </div>

      <DataTable
        data={shown}
        columns={columns}
        getRowId={(f) => f.path}
        isLoading={files.isLoading}
        isFetching={files.isFetching}
        error={files.error}
        loadingLabel="Loading workspace files"
        emptyMessage="No files."
        rowActions={(f) =>
          f.kind === 'other' ? null : (
            <Button
              size="sm"
              variant="outline"
              isLoading={openingPath === f.path}
              leadingIcon={<Eye className="size-4" aria-hidden="true" />}
              onClick={() => void open(f)}
            >
              Preview
            </Button>
          )
        }
      />

      {opened ? <Viewer projectId={project.id} opened={opened} onClose={close} /> : null}
    </div>
  )
}

function Viewer({
  projectId,
  opened,
  onClose,
}: {
  projectId: string
  opened: Opened
  onClose: () => void
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const Icon =
    opened.kind === 'table' ? Sheet : opened.kind === 'image' ? Image : FileText

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgb(var(--background))]/80 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={opened.file.path}
    >
      <div className="flex h-[90vh] w-full max-w-6xl flex-col gap-3 rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4 shadow-xl">
        <div className="flex items-center justify-between gap-3">
          <h2 className="flex min-w-0 items-center gap-2 font-mono text-sm font-bold">
            <Icon className="size-4 shrink-0" aria-hidden="true" />
            <span className="truncate">{opened.file.path}</span>
          </h2>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </div>
        {opened.kind === 'table' ? (
          <TableView projectId={projectId} path={opened.file.path} />
        ) : opened.kind === 'pdf' ? (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded border border-[rgb(var(--border))]">
            <PdfViewer url={opened.url} name={opened.file.path} />
          </div>
        ) : opened.kind === 'image' ? (
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto bg-black">
            <img
              src={opened.url}
              alt={opened.file.path}
              className="max-h-full max-w-full"
            />
          </div>
        ) : opened.kind === 'text' ? (
          <div className="min-h-0 flex-1 overflow-auto rounded border border-[rgb(var(--border))] p-3">
            {opened.truncated ? (
              <p className={`mb-2 ${mutedClass}`}>Only the first 512 KB are shown.</p>
            ) : null}
            <pre className="font-mono text-xs whitespace-pre-wrap">{opened.text}</pre>
          </div>
        ) : null}
      </div>
    </div>
  )
}

function TableView({ projectId, path }: { projectId: string; path: string }) {
  const [sheet, setSheet] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [typed, setTyped] = useState('')
  const [query, setQuery] = useState('')

  // Search after a short pause, not on every key press (each request is logged).
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(typed.trim())
      setPage(1)
    }, 400)
    return () => clearTimeout(timer)
  }, [typed])

  const table = useWorkspaceTable(projectId, path, sheet, page, query, PAGE_SIZE)
  const data = table.data
  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        {data && data.sheets.length > 1 ? (
          <div className="w-56">
            <SelectField
              label="Sheet"
              value={data.sheet ?? ''}
              options={data.sheets.map((name) => ({ value: name, label: name }))}
              onChange={(event) => {
                setSheet(event.target.value)
                setPage(1)
              }}
            />
          </div>
        ) : null}
        <div className="w-72">
          <TextField
            label="Search rows"
            value={typed}
            placeholder="any value in the row"
            onChange={(event) => setTyped(event.target.value)}
          />
        </div>
        <div className="ml-auto flex items-center gap-2 text-sm">
          <span className={mutedClass}>
            {data
              ? `${data.total} row(s)${data.truncated ? ' (search stopped early)' : ''}`
              : ''}
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={page <= 1 || table.isFetching}
            aria-label="Previous page"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            <ChevronLeft className="size-4" aria-hidden="true" />
          </Button>
          <span>
            {page} / {pages}
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={page >= pages || table.isFetching}
            aria-label="Next page"
            onClick={() => setPage((p) => p + 1)}
          >
            <ChevronRight className="size-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      {table.isLoading ? (
        <LoadingBlock label="Loading table" />
      ) : table.error ? (
        <p className="text-sm text-[rgb(var(--danger))]">
          {table.error instanceof ApiError
            ? table.error.message
            : 'Could not read the table'}
        </p>
      ) : data ? (
        <div className="min-h-0 flex-1 overflow-auto rounded border border-[rgb(var(--border))]">
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 bg-[rgb(var(--background-secondary))]">
              <tr>
                {data.columns.map((column, index) => (
                  <th
                    key={index}
                    className="border-b border-[rgb(var(--border))] px-2 py-1.5 text-left font-semibold whitespace-nowrap"
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, rowIndex) => (
                <tr
                  key={rowIndex}
                  className="odd:bg-[rgb(var(--background-secondary))]/40"
                >
                  {row.map((cell, cellIndex) => (
                    <td
                      key={cellIndex}
                      className="border-b border-[rgb(var(--border))] px-2 py-1 align-top whitespace-nowrap"
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
              {data.rows.length === 0 ? (
                <tr>
                  <td
                    className={`px-2 py-3 ${mutedClass}`}
                    colSpan={data.columns.length || 1}
                  >
                    No rows.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}
