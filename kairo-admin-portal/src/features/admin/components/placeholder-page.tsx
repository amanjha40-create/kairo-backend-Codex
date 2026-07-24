export function AdminPlaceholderPage({ title, purpose }: { title: string; purpose: string }) {
  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-6">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-foreground">{title}</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">{purpose}</p>
      </header>
      <div className="rounded-lg border border-dashed border-border bg-card/50 p-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Status</p>
        <p className="mt-1 text-sm text-foreground">Planned for the next build phase.</p>
      </div>
    </div>
  );
}
