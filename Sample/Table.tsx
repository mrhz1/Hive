import * as React from "react";
import { cn } from "@/lib/utils";
import { tableVariants, rowVariants, cellVariants } from "./Table.styles";
import { type TableProps, type TableRowProps, type TableCellProps } from "./Table.types";

const Table = React.forwardRef<HTMLTableElement, TableProps>(({ className, ...props }, ref) => (
  <div className="relative w-full rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] shadow-sm">
    <table ref={ref} className={cn(tableVariants(), className)} {...props} />
  </div>
));
Table.displayName = "Table";

const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead ref={ref} className={cn("bg-[rgb(var(--background-secondary))]", className)} {...props} />
));
TableHeader.displayName = "TableHeader";

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody ref={ref} className={cn("divide-y divide-[rgb(var(--border))]", className)} {...props} />
));
TableBody.displayName = "TableBody";

const TableRow = React.forwardRef<HTMLTableRowElement, TableRowProps>(
  ({ className, isHoverable, ...props }, ref) => (
    <tr ref={ref} className={cn(rowVariants({ isHoverable, className }))} {...props} />
  ),
);
TableRow.displayName = "TableRow";

const TableHead = React.forwardRef<HTMLTableCellElement, TableCellProps>(
  ({ className, isNumeric, ...props }, ref) => (
    <th
      ref={ref}
      className={cn(cellVariants({ isHeader: true, isNumeric, className }))}
      {...props}
    />
  ),
);
TableHead.displayName = "TableHead";

const TableCell = React.forwardRef<HTMLTableCellElement, TableCellProps>(
  ({ className, isNumeric, colSpan, ...props }, ref) => (
    <td
      colSpan={colSpan}
      ref={ref}
      className={cn(cellVariants({ isHeader: false, isNumeric, className }))}
      {...props}
    />
  ),
);
TableCell.displayName = "TableCell";

/**
 * TablePagination: The footer container for table navigation
 */
const TablePagination = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "px-6 py-4 bg-[rgb(var(--background-secondary))] border-t border-[rgb(var(--border))] flex flex-col sm:flex-row items-center justify-between gap-4",
        className,
      )}
      {...props}
    />
  ),
);
TablePagination.displayName = "TablePagination";

/**
 * TablePaginationInfo: Displays "Rows per page" and "Total"
 */
const TablePaginationInfo = ({
  total,
  pageSize,
  onPageSizeChange,
}: {
  total: number;
  pageSize: number;
  onPageSizeChange: (size: number) => void;
}) => (
  <div className="flex items-center gap-6">
    <div className="flex items-center gap-2">
      <label
        htmlFor="rows-per-page"
        className="text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--foreground-muted))]"
      >
        Rows:
      </label>
      <select
        id="rows-per-page"
        value={pageSize}
        onChange={(e) => {
          onPageSizeChange(Number(e.target.value));
        }}
        className="bg-[rgb(var(--surface))] border border-[rgb(var(--border))] rounded-md px-2 py-1 text-xs font-bold text-[rgb(var(--foreground))] focus:ring-2 focus:ring-[rgb(var(--primary))/0.2] focus:border-[rgb(var(--primary))] outline-none cursor-pointer transition-all"
      >
        {[5, 10, 20, 50].map((size) => (
          <option key={size} value={size}>
            {size}
          </option>
        ))}
      </select>
    </div>
    <p className="text-sm text-[rgb(var(--foreground-muted))] font-medium">
      Total records:{" "}
      <span className="text-[rgb(var(--foreground))] font-bold tabular-nums">{total}</span>
    </p>
  </div>
);

export {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
  TablePagination,
  TablePaginationInfo,
};
