import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
} from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { Button } from './ui/Button'
import { Spinner } from './ui/Spinner'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TablePagination,
  TablePaginationInfo,
  TableRow,
} from './ui/Table'

/** Values a column can be sorted on. */
export type SortValue = string | number | boolean | null | undefined

export type Column<T> = {
  /** Stable identity for React keys and sort state. */
  id: string
  header: string
  /** Rendered per row -- keeps formatting out of the table itself. */
  cell: (row: T) => ReactNode
  /**
   * Makes the column sortable. Returns the raw comparable value, because
   * `cell` returns a ReactNode which cannot be ordered reliably -- a
   * badge or a link would sort by its markup, not its meaning.
   */
  sortValue?: (row: T) => SortValue
  /** Right-aligns and tabular-nums the column. */
  isNumeric?: boolean
  className?: string
}

export type DataTableProps<T> = {
  data: T[] | undefined
  columns: Array<Column<T>>
  getRowId: (row: T) => string
  isLoading?: boolean
  isFetching?: boolean
  error?: unknown
  emptyMessage?: string
  /** Right-aligned per-row actions (edit/delete). */
  rowActions?: (row: T) => ReactNode
  loadingLabel?: string
}

type SortState = { id: string; direction: 'asc' | 'desc' }

/** Nulls sort last in both directions; strings compare case-insensitively. */
function compare(a: SortValue, b: SortValue): number {
  const aEmpty = a === null || a === undefined || a === ''
  const bEmpty = b === null || b === undefined || b === ''
  if (aEmpty && bEmpty) return 0
  if (aEmpty) return 1
  if (bEmpty) return -1

  if (typeof a === 'number' && typeof b === 'number') return a - b
  if (typeof a === 'boolean' && typeof b === 'boolean') {
    return a === b ? 0 : a ? -1 : 1
  }
  return String(a).localeCompare(String(b), undefined, {
    sensitivity: 'base',
    numeric: true,
  })
}

/**
 * The single table used by every list page.
 *
 * Sorting and pagination are client side because the API returns whole
 * collections; doing either server side would cost an extra Hive query
 * per interaction for no benefit at these row counts.
 */
export function DataTable<T>({
  data,
  columns,
  getRowId,
  isLoading = false,
  isFetching = false,
  error,
  emptyMessage = 'No records found.',
  rowActions,
  loadingLabel = 'Loading',
}: DataTableProps<T>) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [sort, setSort] = useState<SortState | null>(null)

  const rows = useMemo(() => data ?? [], [data])

  const sortedRows = useMemo(() => {
    if (!sort) return rows
    const column = columns.find((c) => c.id === sort.id)
    if (!column?.sortValue) return rows

    const getValue = column.sortValue
    // Copy before sorting: the array comes from the query cache and
    // sorting in place would mutate cached data.
    return [...rows].sort((a, b) => {
      const result = compare(getValue(a), getValue(b))
      return sort.direction === 'asc' ? result : -result
    })
  }, [rows, sort, columns])

  const total = sortedRows.length
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  // A delete on the last page (or a shrinking filter) can leave `page`
  // beyond the end. Clamping on read rather than correcting it in an
  // effect avoids a second render pass and keeps this a pure derivation.
  const currentPage = Math.min(page, totalPages)

  const pageRows = useMemo(
    () => sortedRows.slice((currentPage - 1) * pageSize, currentPage * pageSize),
    [sortedRows, currentPage, pageSize]
  )

  const columnCount = columns.length + (rowActions ? 1 : 0)

  // Refetching while rows are already on screen (e.g. after a create or
  // update invalidates the cache). Distinct from `isLoading`, which is
  // the first load with nothing to show.
  const isRefreshing = isFetching && !isLoading

  function toggleSort(columnId: string) {
    setPage(1)
    setSort((current) => {
      if (current?.id !== columnId) return { id: columnId, direction: 'asc' }
      if (current.direction === 'asc') return { id: columnId, direction: 'desc' }
      // Third click clears the sort and restores the API's own order.
      return null
    })
  }

  return (
    <div className="flex flex-col space-y-4">
      <div className="relative">
        {/* Refetch overlay: keeps the stale rows visible underneath but
            makes it obvious the table is updating. Without this a slow
            Hive refetch after a mutation looks like nothing happened. */}
        {isRefreshing ? (
          <div
            className="absolute inset-0 z-20 flex items-start justify-center rounded-xl bg-[rgb(var(--surface))]/60 backdrop-blur-[1px]"
            role="status"
            aria-live="polite"
          >
            <div className="mt-24 flex items-center gap-3 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] px-4 py-2.5 shadow-lg">
              <Spinner size="sm" label="" />
              <span className="text-sm font-semibold text-[rgb(var(--foreground))]">
                Updating…
              </span>
            </div>
          </div>
        ) : null}

        <Table>
          <TableHeader>
            <TableRow isHoverable={false}>
              {columns.map((column) => {
                const isSorted = sort?.id === column.id
                const ariaSort = isSorted
                  ? sort.direction === 'asc'
                    ? 'ascending'
                    : 'descending'
                  : 'none'

                return (
                  <TableHead
                    key={column.id}
                    isNumeric={column.isNumeric}
                    aria-sort={column.sortValue ? ariaSort : undefined}
                  >
                    {column.sortValue ? (
                      <button
                        type="button"
                        onClick={() => toggleSort(column.id)}
                        className={cn(
                          'group inline-flex items-center gap-1.5 rounded transition-colors hover:text-teal-600 dark:hover:text-teal-400',
                          column.isNumeric && 'flex-row-reverse',
                          isSorted && 'text-teal-600 dark:text-teal-400'
                        )}
                        aria-label={`Sort by ${column.header}`}
                      >
                        {column.header}
                        {isSorted ? (
                          sort.direction === 'asc' ? (
                            <ArrowUp size={12} strokeWidth={3} aria-hidden="true" />
                          ) : (
                            <ArrowDown size={12} strokeWidth={3} aria-hidden="true" />
                          )
                        ) : (
                          <ChevronsUpDown
                            size={12}
                            strokeWidth={2.5}
                            aria-hidden="true"
                            className="opacity-0 transition-opacity group-hover:opacity-60"
                          />
                        )}
                      </button>
                    ) : (
                      column.header
                    )}
                  </TableHead>
                )
              })}
              {rowActions ? (
                // Pinned to the right edge so Edit/Delete stay reachable
                // if the table ever scrolls sideways.
                <TableHead
                  isNumeric
                  className="sticky right-0 z-10 bg-[rgb(var(--background-secondary))]"
                >
                  Actions
                </TableHead>
              ) : null}
            </TableRow>
          </TableHeader>

          <TableBody>
            {isLoading ? (
              <TableRow isHoverable={false}>
                <TableCell colSpan={columnCount}>
                  <div className="flex items-center justify-center gap-3 py-10">
                    <Spinner size="md" label="" />
                    <span className="text-sm text-[rgb(var(--foreground-muted))]">
                      {loadingLabel}…
                    </span>
                  </div>
                </TableCell>
              </TableRow>
            ) : error ? (
              <TableRow isHoverable={false}>
                <TableCell colSpan={columnCount}>
                  <div className="py-10 text-center text-sm text-rose-600 dark:text-rose-400">
                    {error instanceof Error ? error.message : 'Failed to load records.'}
                  </div>
                </TableCell>
              </TableRow>
            ) : total === 0 ? (
              <TableRow isHoverable={false}>
                <TableCell colSpan={columnCount}>
                  <div className="py-10 text-center text-sm text-[rgb(var(--foreground-muted))]">
                    {emptyMessage}
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              pageRows.map((row) => (
                <TableRow key={getRowId(row)}>
                  {columns.map((column) => (
                    <TableCell
                      key={column.id}
                      isNumeric={column.isNumeric}
                      className={column.className}
                    >
                      {column.cell(row)}
                    </TableCell>
                  ))}
                  {rowActions ? (
                    // flex + nowrap keeps Edit/Delete on one line; inline
                    // buttons wrap in the narrow actions column and double
                    // the row height.
                    <TableCell className="sticky right-0 z-10 bg-[rgb(var(--surface))] whitespace-nowrap group-hover/row:bg-[rgb(var(--background-secondary))]">
                      <div className="flex items-center justify-end gap-2">
                        {rowActions(row)}
                      </div>
                    </TableCell>
                  ) : null}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <TablePagination>
        <TablePaginationInfo
          total={total}
          pageSize={pageSize}
          onPageSizeChange={(size) => {
            setPageSize(size)
            setPage(1)
          }}
        />

        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-[rgb(var(--foreground-muted))] tabular-nums">
            Page {currentPage} of {totalPages}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              aria-label="Previous page"
              disabled={currentPage === 1}
              onClick={() => setPage(Math.max(1, currentPage - 1))}
            >
              <ChevronLeft size={16} />
            </Button>
            <Button
              variant="outline"
              size="sm"
              aria-label="Next page"
              disabled={currentPage >= totalPages}
              onClick={() => setPage(Math.min(totalPages, currentPage + 1))}
            >
              <ChevronRight size={16} />
            </Button>
          </div>
        </div>
      </TablePagination>
    </div>
  )
}
