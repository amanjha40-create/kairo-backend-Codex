import { useState, type ReactNode } from "react";
import { ChevronDown, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface Option {
  value: string;
  label: string;
}

interface Props {
  label: string;
  options: Option[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
}

/**
 * Compact multi-select popover used inside the admin filter bar.
 * Keyboard-accessible: trigger + checkboxes are native controls.
 */
export function FilterMultiSelect({ label, options, selected, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const count = selected.size;
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={cn(
          "inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-2 text-xs font-medium text-foreground hover:bg-accent",
          count > 0 && "border-foreground/40",
        )}
      >
        <span className="text-muted-foreground">{label}</span>
        {count > 0 ? (
          <span className="rounded bg-foreground px-1.5 text-[10px] font-semibold text-background tabular-nums">
            {count}
          </span>
        ) : null}
        <ChevronDown aria-hidden className="size-3 text-muted-foreground" />
      </button>
      {open ? (
        <>
          <button
            aria-label="Close filter"
            className="fixed inset-0 z-10 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div
            role="listbox"
            aria-multiselectable
            aria-label={label}
            className="absolute z-20 mt-1 w-56 rounded-md border border-border bg-popover p-1 shadow-md"
          >
            {options.map((opt) => {
              const checked = selected.has(opt.value);
              return (
                <label
                  key={opt.value}
                  className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs text-popover-foreground hover:bg-accent"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => {
                      const next = new Set(selected);
                      if (checked) next.delete(opt.value);
                      else next.add(opt.value);
                      onChange(next);
                    }}
                    className="size-3.5 rounded border-border accent-foreground"
                  />
                  <span className="flex-1">{opt.label}</span>
                </label>
              );
            })}
            {count > 0 ? (
              <button
                type="button"
                onClick={() => onChange(new Set())}
                className="mt-1 flex w-full items-center justify-center gap-1 rounded border-t border-border px-2 py-1.5 text-[11px] text-muted-foreground hover:text-foreground"
              >
                <X aria-hidden className="size-3" /> Clear {label.toLowerCase()}
              </button>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}

export function FilterBar({
  children,
  activeCount,
  onClear,
}: {
  children: ReactNode;
  activeCount: number;
  onClear: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {children}
      {activeCount > 0 ? (
        <button
          type="button"
          onClick={onClear}
          className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs font-medium text-muted-foreground hover:text-foreground"
        >
          <X aria-hidden className="size-3" /> Clear all
          <span className="ml-1 rounded bg-muted px-1.5 py-0.5 text-[10px] tabular-nums">
            {activeCount}
          </span>
        </button>
      ) : null}
    </div>
  );
}
