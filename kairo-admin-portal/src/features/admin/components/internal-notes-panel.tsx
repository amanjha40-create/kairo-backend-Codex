import { useState } from "react";
import { StickyNote } from "lucide-react";
import { EmptyState } from "./states";
import { NOTE_CATEGORY_LABEL, type InternalNote, type NoteCategory } from "../data/cases";
import { formatRelativeTime } from "../lib/format";

const CATEGORY_ORDER: NoteCategory[] = [
  "general",
  "evidence",
  "organization",
  "contact",
  "risk",
  "decision_preparation",
];

export function InternalNotesPanel({
  notes,
  onAdd,
  author,
  role,
}: {
  notes: InternalNote[];
  onAdd: (body: string, category: NoteCategory) => void;
  author: string;
  role: string;
}) {
  const [body, setBody] = useState("");
  const [category, setCategory] = useState<NoteCategory>("general");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = body.trim();
    if (!trimmed) return;
    onAdd(trimmed, category);
    setBody("");
    setCategory("general");
  }

  return (
    <div className="flex flex-col gap-3">
      <form onSubmit={submit} className="rounded-md border border-border bg-background p-3">
        <label htmlFor="internal-note-body" className="sr-only">
          Internal note
        </label>
        <textarea
          id="internal-note-body"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder={`Add an internal note as ${author}. Never visible to candidates or employers.`}
          rows={3}
          className="block w-full resize-y rounded border border-border bg-background px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs">
            <label htmlFor="internal-note-cat" className="text-muted-foreground">
              Category
            </label>
            <select
              id="internal-note-cat"
              value={category}
              onChange={(e) => setCategory(e.target.value as NoteCategory)}
              className="h-7 rounded border border-border bg-background px-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            >
              {CATEGORY_ORDER.map((c) => (
                <option key={c} value={c}>
                  {NOTE_CATEGORY_LABEL[c]}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={!body.trim()}
            className="inline-flex h-7 items-center gap-1 rounded-md bg-foreground px-2 text-xs font-medium text-background hover:bg-foreground/90 disabled:opacity-50"
          >
            <StickyNote aria-hidden className="size-3" />
            Add note (session-only)
          </button>
        </div>
      </form>

      {notes.length === 0 ? (
        <EmptyState
          title="No internal notes yet"
          description="Notes are visible only to Kairo operators. Add one above to start a discussion."
        />
      ) : (
        <ul className="space-y-2">
          {notes
            .slice()
            .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())
            .map((n) => (
              <li key={n.id} className="rounded-md border border-border bg-background p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
                  <p className="text-xs font-medium text-foreground">
                    {n.author} <span className="font-normal text-muted-foreground">· {n.role}</span>
                  </p>
                  <p className="text-[11px] tabular-nums text-muted-foreground">
                    {formatRelativeTime(n.at)}
                  </p>
                </div>
                <p className="mt-1 whitespace-pre-wrap text-xs text-foreground">{n.body}</p>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                    {NOTE_CATEGORY_LABEL[n.category]}
                  </span>
                  <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium text-zinc-700 dark:bg-zinc-800/60 dark:text-zinc-300">
                    Internal only
                  </span>
                  {n.sessionOnly ? (
                    <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-700 ring-1 ring-inset ring-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:ring-sky-900/60">
                      Session-only
                    </span>
                  ) : null}
                </div>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
