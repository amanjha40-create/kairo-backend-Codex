import { ChevronLeft, ChevronRight } from "lucide-react";

interface Props {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  pageSizeOptions?: number[];
}

export function TablePagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [10, 25, 50],
}: Props) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, totalPages);
  const from = total === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const to = Math.min(total, safePage * pageSize);

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border bg-card px-3 py-2 text-xs">
      <div className="flex items-center gap-2 text-muted-foreground">
        <label className="flex items-center gap-1.5">
          <span>Rows</span>
          <select
            value={pageSize}
            onChange={(e) => onPageSizeChange(Number(e.target.value))}
            className="h-7 rounded border border-border bg-background px-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            aria-label="Rows per page"
          >
            {pageSizeOptions.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <span aria-live="polite">
          <span className="tabular-nums text-foreground">
            {from}–{to}
          </span>{" "}
          of <span className="tabular-nums text-foreground">{total}</span>
        </span>
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onPageChange(Math.max(1, safePage - 1))}
          disabled={safePage <= 1}
          aria-label="Previous page"
          className="inline-flex size-7 items-center justify-center rounded border border-border bg-background text-muted-foreground disabled:cursor-not-allowed disabled:opacity-40 hover:enabled:bg-accent hover:enabled:text-foreground"
        >
          <ChevronLeft aria-hidden className="size-3.5" />
        </button>
        <span className="px-2 tabular-nums text-foreground">
          Page {safePage} <span className="text-muted-foreground">/ {totalPages}</span>
        </span>
        <button
          onClick={() => onPageChange(Math.min(totalPages, safePage + 1))}
          disabled={safePage >= totalPages}
          aria-label="Next page"
          className="inline-flex size-7 items-center justify-center rounded border border-border bg-background text-muted-foreground disabled:cursor-not-allowed disabled:opacity-40 hover:enabled:bg-accent hover:enabled:text-foreground"
        >
          <ChevronRight aria-hidden className="size-3.5" />
        </button>
      </div>
    </div>
  );
}
