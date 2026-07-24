import type { ReactNode } from "react";
import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react";
import { cn } from "@/lib/utils";

export type SortDirection = "asc" | "desc" | null;

export interface AdminTableColumn<T> {
  id: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  sortable?: boolean;
  className?: string;
  headerClassName?: string;
  align?: "left" | "right" | "center";
}

interface Props<T> {
  columns: AdminTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  selection?: {
    selectedIds: Set<string>;
    onToggle: (id: string) => void;
    onToggleAll: (ids: string[]) => void;
  };
  sort?: { id: string; direction: SortDirection };
  onSortChange?: (id: string) => void;
  empty?: ReactNode;
  ariaLabel: string;
}

export function AdminDataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  selection,
  sort,
  onSortChange,
  empty,
  ariaLabel,
}: Props<T>) {
  const allIds = rows.map(rowKey);
  const allSelected =
    selection && allIds.length > 0 && allIds.every((id) => selection.selectedIds.has(id));
  const someSelected =
    selection && !allSelected && allIds.some((id) => selection.selectedIds.has(id));

  return (
    <div className="w-full overflow-x-auto">
      <table
        className="w-full min-w-[1080px] border-separate border-spacing-0 text-left text-sm"
        aria-label={ariaLabel}
      >
        <thead>
          <tr className="bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground">
            {selection ? (
              <th scope="col" className="sticky top-0 w-9 border-b border-border px-3 py-2">
                <input
                  type="checkbox"
                  aria-label={allSelected ? "Deselect all" : "Select all rows"}
                  checked={!!allSelected}
                  ref={(el) => {
                    if (el) el.indeterminate = !!someSelected;
                  }}
                  onChange={() => selection.onToggleAll(allIds)}
                  className="size-3.5 cursor-pointer rounded border-border accent-foreground"
                />
              </th>
            ) : null}
            {columns.map((col) => {
              const active = sort?.id === col.id ? sort.direction : null;
              const alignClass =
                col.align === "right"
                  ? "text-right"
                  : col.align === "center"
                    ? "text-center"
                    : "text-left";
              return (
                <th
                  key={col.id}
                  scope="col"
                  aria-sort={
                    active === "asc"
                      ? "ascending"
                      : active === "desc"
                        ? "descending"
                        : col.sortable
                          ? "none"
                          : undefined
                  }
                  className={cn(
                    "border-b border-border px-3 py-2 font-medium",
                    alignClass,
                    col.headerClassName,
                  )}
                >
                  {col.sortable && onSortChange ? (
                    <button
                      type="button"
                      onClick={() => onSortChange(col.id)}
                      className="inline-flex items-center gap-1 hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {col.header}
                      {active === "asc" ? (
                        <ChevronUp aria-hidden className="size-3" />
                      ) : active === "desc" ? (
                        <ChevronDown aria-hidden className="size-3" />
                      ) : (
                        <ChevronsUpDown aria-hidden className="size-3 opacity-50" />
                      )}
                    </button>
                  ) : (
                    col.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length + (selection ? 1 : 0)}
                className="px-3 py-10 text-center text-muted-foreground"
              >
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row) => {
              const id = rowKey(row);
              const selected = selection?.selectedIds.has(id) ?? false;
              return (
                <tr
                  key={id}
                  tabIndex={onRowClick ? 0 : undefined}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  onKeyDown={
                    onRowClick
                      ? (e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            onRowClick(row);
                          }
                        }
                      : undefined
                  }
                  aria-selected={selection ? selected : undefined}
                  className={cn(
                    "group border-b border-border transition-colors",
                    onRowClick &&
                      "cursor-pointer hover:bg-accent/50 focus:outline-none focus-visible:bg-accent/60",
                    selected && "bg-accent/40",
                  )}
                >
                  {selection ? (
                    <td
                      className="border-b border-border px-3 py-2.5"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <input
                        type="checkbox"
                        aria-label={`Select row ${id}`}
                        checked={selected}
                        onChange={() => selection.onToggle(id)}
                        className="size-3.5 cursor-pointer rounded border-border accent-foreground"
                      />
                    </td>
                  ) : null}
                  {columns.map((col) => (
                    <td
                      key={col.id}
                      className={cn(
                        "border-b border-border px-3 py-2.5 align-top text-sm",
                        col.align === "right" && "text-right",
                        col.align === "center" && "text-center",
                        col.className,
                      )}
                    >
                      {col.cell(row)}
                    </td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
