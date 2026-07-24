import { createFileRoute, Link, notFound } from "@tanstack/react-router";
import { ArrowLeft, Building2, ChevronRight, ExternalLink } from "lucide-react";
import { WorkspaceSection } from "@/features/admin/components/workspace-section";
import { EmptyState } from "@/features/admin/components/states";
import { formatRelativeTime } from "@/features/admin/lib/format";
import {
  REGISTRY_CONTACT_ROLE_LABEL,
  REGISTRY_CONTACT_STATE_LABEL,
  REGISTRY_ORG_STATE_LABEL,
  REGISTRY_ORG_TYPE_LABEL,
  getRegistryOrganization,
  type RegistryOrganization,
} from "@/features/admin/data/registry";

export const Route = createFileRoute("/admin/registry/$organizationId")({
  head: () => ({
    meta: [
      { title: "Registry organization — Kairo Admin" },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  loader: ({ params }) => {
    const org = getRegistryOrganization(params.organizationId);
    if (!org) throw notFound();
    return { org };
  },
  component: RegistryOrgDetail,
  notFoundComponent: () => (
    <div className="mx-auto max-w-2xl">
      <EmptyState
        title="Organization not found"
        description="The registry record may have been merged or removed."
        action={
          <Link
            to="/admin/registry"
            className="inline-flex h-8 items-center rounded-md bg-foreground px-3 text-xs font-medium text-background hover:bg-foreground/90"
          >
            Back to Registry
          </Link>
        }
      />
    </div>
  ),
});

function RegistryOrgDetail() {
  const { org } = Route.useLoaderData() as { org: RegistryOrganization };

  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-4">
      <nav
        aria-label="Breadcrumb"
        className="flex items-center gap-1.5 text-xs text-muted-foreground"
      >
        <Link to="/admin/registry" className="inline-flex items-center gap-1 hover:text-foreground">
          <ArrowLeft aria-hidden className="size-3" />
          Registry
        </Link>
        <ChevronRight aria-hidden className="size-3" />
        <span className="text-foreground">{org.canonicalName}</span>
      </nav>

      <header className="rounded-lg border border-border bg-card px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <Building2 aria-hidden className="size-4 text-muted-foreground" />
              <h1 className="truncate text-base font-semibold tracking-tight text-foreground">
                {org.canonicalName}
              </h1>
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-foreground">
                {REGISTRY_ORG_STATE_LABEL[org.state]}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {REGISTRY_ORG_TYPE_LABEL[org.orgType]} · {org.country}
              {org.headquartersCity ? ` · ${org.headquartersCity}` : ""}
              {org.yearFounded ? ` · Founded ${org.yearFounded}` : ""}
              {org.employeesRange ? ` · ${org.employeesRange} employees` : ""}
            </p>
            {org.aliases.length > 0 ? (
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                Aliases: {org.aliases.join(", ")}
              </p>
            ) : null}
          </div>
          <div className="text-right text-[11px] text-muted-foreground">
            <a
              href={org.website}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-foreground hover:underline"
            >
              {org.domain}
              <ExternalLink aria-hidden className="size-3" />
            </a>
            <div className="mt-1">
              Active cases: <span className="text-foreground">{org.activeCaseCount}</span>
            </div>
            <div>
              Total verifications: <span className="text-foreground">{org.totalVerifications}</span>
            </div>
          </div>
        </div>
        {org.description ? <p className="mt-2 text-xs text-foreground">{org.description}</p> : null}
      </header>

      {org.possibleDuplicateIds.length > 0 ? (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-[11px] text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <div className="font-semibold">Possible duplicate detected</div>
          <ul className="ml-4 mt-1 list-disc">
            {org.possibleDuplicateIds.map((id) => {
              const other = getRegistryOrganization(id);
              return (
                <li key={id}>
                  {other ? (
                    <Link
                      to="/admin/registry/$organizationId"
                      params={{ organizationId: id }}
                      className="hover:underline"
                    >
                      {other.canonicalName}
                    </Link>
                  ) : (
                    id
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <WorkspaceSection
          title="Verification contacts"
          description={`${org.contacts.length} contact${org.contacts.length === 1 ? "" : "s"} on file. Session-only edits happen on a case workspace.`}
        >
          {org.contacts.length === 0 ? (
            <EmptyState
              title="No contacts on file"
              description="Add contacts from a case workspace when preparing outreach."
            />
          ) : (
            <ul className="divide-y divide-border">
              {org.contacts.map((c) => (
                <li key={c.id} className="py-2 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="font-medium text-foreground">{c.name}</span>
                        <span className="text-muted-foreground">
                          · {REGISTRY_CONTACT_ROLE_LABEL[c.role]}
                        </span>
                      </div>
                      <div className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                        {c.emailMasked}
                        {c.phoneMasked ? ` · ${c.phoneMasked}` : ""}
                      </div>
                      <div className="text-[11px] text-muted-foreground">
                        Added by {c.addedBy} · {formatRelativeTime(c.addedAt)}
                        {c.lastSuccessfulUse
                          ? ` · Last used ${formatRelativeTime(c.lastSuccessfulUse)}`
                          : ""}
                      </div>
                    </div>
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-foreground">
                      {REGISTRY_CONTACT_STATE_LABEL[c.state]}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </WorkspaceSection>

        <WorkspaceSection
          title="Activity"
          description="Timeline of significant events on this registry record."
        >
          {org.activity.length === 0 ? (
            <EmptyState title="No activity yet" />
          ) : (
            <ol className="space-y-2 border-l border-border pl-3 text-[11px]">
              {org.activity
                .slice()
                .reverse()
                .map((e) => (
                  <li key={e.id}>
                    <div className="text-foreground">{e.description}</div>
                    <div className="text-muted-foreground">
                      {e.actor} · {formatRelativeTime(e.at)}
                    </div>
                  </li>
                ))}
            </ol>
          )}
        </WorkspaceSection>
      </div>
    </div>
  );
}
