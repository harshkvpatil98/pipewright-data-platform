import { Icon } from "./icon";
import { cx } from "./internal/cx";

type TableProps = React.TableHTMLAttributes<HTMLTableElement> & {
  /** Below this width the table scrolls sideways instead of squashing its columns. */
  minWidth?: number;
  /** Tighter rows for long lists people scan rather than read. */
  dense?: boolean;
  /**
   * Where the first and last columns sit: flush with the text around the
   * table (inside a padded panel), or inset to the panel's own padding when
   * the table runs edge to edge.
   */
  edge?: "flush" | "panel";
};

/**
 * Every list of rows in the product. Rows, header cells and data cells take
 * their spacing from the density setting, so a table looks the same wherever
 * it appears and follows the person's comfortable or compact choice.
 */
export function Table({ minWidth, dense = false, edge = "flush", className, style, children, ...props }: TableProps) {
  return (
    <div className="overflow-x-auto">
      <table
        className={cx(
          "w-full border-collapse text-left text-ink",
          dense ? "text-[13px] [&_td]:py-1.5 [&_th]:py-1.5" : "text-[14px]",
          edge === "flush"
            ? "[&_tr>*:first-child]:pl-0 [&_tr>*:last-child]:pr-0"
            : "[&_tr>*:first-child]:pl-5 [&_tr>*:last-child]:pr-5 lg:[&_tr>*:first-child]:pl-6 lg:[&_tr>*:last-child]:pr-6",
          className,
        )}
        style={minWidth ? { minWidth, ...style } : style}
        {...props}
      >
        {children}
      </table>
    </div>
  );
}

export function TableHead({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cx("text-[13px] text-ink-3", className)} {...props} />;
}

export function TableBody({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cx("[&>tr:last-child]:border-b-0 [&>tr]:transition [&>tr:hover]:bg-surface", className)} {...props} />;
}

export function TableRow({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cx("border-b border-line align-top", className)} {...props} />;
}

type TableHeaderCellProps = React.ThHTMLAttributes<HTMLTableCellElement> & {
  /** Numbers line up on the right. */
  numeric?: boolean;
  /** Set on a sortable column: the current direction, or null when the table is sorted by another column. */
  sort?: "asc" | "desc" | null;
  onSort?: () => void;
};

export function TableHeaderCell({ numeric, sort, onSort, className, children, ...props }: TableHeaderCellProps) {
  const sortable = onSort !== undefined;
  return (
    <th
      scope="col"
      aria-sort={sortable ? (sort === "asc" ? "ascending" : sort === "desc" ? "descending" : "none") : undefined}
      className={cx("cell-pad whitespace-nowrap font-medium", numeric && "text-right", className)}
      {...props}
    >
      {sortable ? (
        <button
          type="button"
          onClick={onSort}
          className={cx("inline-flex items-center gap-1 transition hover:text-ink", sort && "text-ink")}
        >
          {children}
          <Icon
            name={sort === "asc" ? "chevronUp" : "chevronDown"}
            size={13}
            className={sort ? "opacity-100" : "opacity-30"}
          />
        </button>
      ) : (
        children
      )}
    </th>
  );
}

type TableCellProps = React.TdHTMLAttributes<HTMLTableCellElement> & {
  /** Numbers line up on the right, in figures of equal width. */
  numeric?: boolean;
};

export function TableCell({ numeric, className, ...props }: TableCellProps) {
  return <td className={cx("cell-pad", numeric && "text-right tabular-nums", className)} {...props} />;
}
