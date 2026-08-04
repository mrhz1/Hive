import {
  forwardRef,
  type HTMLAttributes,
  type TdHTMLAttributes,
  type ThHTMLAttributes,
} from 'react'
import { cn } from '@/lib/cn'
import { cellVariants, rowVariants, tableVariants } from './Table.styles'

/** Card-wrapped table. overflow-x-auto keeps wide tables usable on narrow
 *  screens without changing the look on desktop. */
export const Table = forwardRef<HTMLTableElement, HTMLAttributes<HTMLTableElement>>(
  function Table({ className, ...props }, ref) {
    return (
      <div className="relative w-full overflow-x-auto rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] shadow-sm">
        <table ref={ref} className={cn(tableVariants(), className)} {...props} />
      </div>
    )
  }
)

export const TableHeader = forwardRef<
  HTMLTableSectionElement,
  HTMLAttributes<HTMLTableSectionElement>
>(function TableHeader({ className, ...props }, ref) {
  return (
    <thead
      ref={ref}
      className={cn('bg-[rgb(var(--background-secondary))]', className)}
      {...props}
    />
  )
})

export const TableBody = forwardRef<
  HTMLTableSectionElement,
  HTMLAttributes<HTMLTableSectionElement>
>(function TableBody({ className, ...props }, ref) {
  return (
    <tbody
      ref={ref}
      className={cn('divide-y divide-[rgb(var(--border))]', className)}
      {...props}
    />
  )
})

export type TableRowProps = HTMLAttributes<HTMLTableRowElement> & {
  isHoverable?: boolean
}

export const TableRow = forwardRef<HTMLTableRowElement, TableRowProps>(function TableRow(
  { className, isHoverable, ...props },
  ref
) {
  return (
    <tr ref={ref} className={cn(rowVariants({ isHoverable, className }))} {...props} />
  )
})

export type TableHeadProps = ThHTMLAttributes<HTMLTableCellElement> & {
  isNumeric?: boolean
}

export const TableHead = forwardRef<HTMLTableCellElement, TableHeadProps>(
  function TableHead({ className, isNumeric, ...props }, ref) {
    return (
      <th
        ref={ref}
        scope="col"
        className={cn(cellVariants({ isHeader: true, isNumeric, className }))}
        {...props}
      />
    )
  }
)

export type TableCellProps = TdHTMLAttributes<HTMLTableCellElement> & {
  isNumeric?: boolean
}

export const TableCell = forwardRef<HTMLTableCellElement, TableCellProps>(
  function TableCell({ className, isNumeric, ...props }, ref) {
    return (
      <td
        ref={ref}
        className={cn(cellVariants({ isHeader: false, isNumeric, className }))}
        {...props}
      />
    )
  }
)

/** Footer container for table navigation. */
export const TablePagination = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  function TablePagination({ className, ...props }, ref) {
    return (
      <div
        ref={ref}
        className={cn(
          'flex flex-col items-center justify-between gap-4 rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] px-6 py-4 sm:flex-row',
          className
        )}
        {...props}
      />
    )
  }
)

/** "Rows per page" plus the total record count. */
export function TablePaginationInfo({
  total,
  pageSize,
  onPageSizeChange,
}: {
  total: number
  pageSize: number
  onPageSizeChange: (size: number) => void
}) {
  return (
    <div className="flex items-center gap-6">
      <div className="flex items-center gap-2">
        <label
          htmlFor="rows-per-page"
          className="text-[10px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase"
        >
          Rows:
        </label>
        <select
          id="rows-per-page"
          value={pageSize}
          onChange={(event) => {
            onPageSizeChange(Number(event.target.value))
          }}
          className="cursor-pointer rounded-md border border-[rgb(var(--border))] bg-[rgb(var(--surface))] px-2 py-1 text-xs font-bold text-[rgb(var(--foreground))] transition-all outline-none focus:border-[rgb(var(--primary))] focus:ring-2 focus:ring-[rgb(var(--primary))]/20"
        >
          {[5, 10, 20, 50].map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
      </div>
      <p className="text-sm font-medium text-[rgb(var(--foreground-muted))]">
        Total records:{' '}
        <span className="font-bold text-[rgb(var(--foreground))] tabular-nums">
          {total}
        </span>
      </p>
    </div>
  )
}
