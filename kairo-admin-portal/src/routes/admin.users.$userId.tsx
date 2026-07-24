import { useMemo, useState } from "react";
import { createFileRoute, Link, notFound, useRouter } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowLeft,
  ChevronRight,
  ExternalLink,
  FileText,
  Fingerprint,
  Mail,
  MapPin,
  Phone,
  Share2,
  ShieldCheck,
  StickyNote,
  Users as UsersIcon,
} from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState } from "@/features/admin/components/states";
import { WorkspaceSection } from "@/features/admin/components/workspace-section";
import { formatRelativeTime } from "@/features/admin/lib/format";
import { useAdminAccess } from "@/features/admin/auth/admin-access";
import { hasPermission } from "@/features/admin/workflow/permissions";
import type { WorkflowPermission } from "@/features/admin/workflow/types";
import { UnsavedChangesDialog } from "@/features/admin/components/unsaved-changes-dialog";
import {
  ACCOUNT_STATUS_LABEL,
  ATTENTION_LABEL,
  ONBOARDING_STEP_LABEL,
  ONBOARDING_STEP_ORDER,
  PASSPORT_STATUS_LABEL,
  PROFILE_TYPE_LABEL,
  TRUST_BAND_LABEL,
  getUser,
  initialsFor,
  type UserAccountStatus,
  type UserRecord,
} from "@/features/admin/data/users";
import {
  USER_ACTION_LABEL,
  USER_NOTE_CATEGORY_LABEL,
  useUserAdminSession,
  type UserAdminActionKind,
  type UserNoteCategory,
} from "@/features/admin/workflow/use-user-admin-session";
import { mockVerificationCases } from "@/features/admin/data/verifications";
import { StatusBadge } from "@/features/admin/components/status-badge";
import { PriorityBadge } from "@/features/admin/components/priority-badge";

export const Route = createFileRoute("/admin/users/$userId")({
  loader: ({ params }) => {
    const user = getUser(params.userId);
    if (!user) throw notFound();
    return { user };
  },
  head: ({ loaderData }) => ({
    meta: [
      {
        title: loaderData
          ? `${loaderData.user.fullName} — Kairo Admin`
          : "User not found — Kairo Admin",
      },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  errorComponent: UserDetailErrorBoundary,
  notFoundComponent: UserDetailNotFound,
  component: UserDetailPage,
});

function UserDetailErrorBoundary({ error, reset }: { error: Error; reset: () => void }) {
  const router = useRouter();

  return (
    <div className="mx-auto max-w-2xl p-8">
      <ErrorState
        title="Something went wrong"
        description={error.message}
        action={
          <button
            type="button"
            onClick={() => {
              router.invalidate();
              reset();
            }}
            className="inline-flex h-8 items-center rounded-md border border-border bg-background px-3 text-xs font-medium hover:bg-accent"
          >
            Retry
          </button>
        }
      />
    </div>
  );
}

function UserDetailNotFound() {
  const { userId } = Route.useParams();

  return (
    <div className="mx-auto max-w-2xl p-8">
      <EmptyState
        title="User not found"
        description={`No user matches "${userId}". They may have been removed or the link is incorrect.`}
        action={
          <Link
            to="/admin/users"
            className="inline-flex h-8 items-center gap-1 rounded-md border border-border bg-background px-3 text-xs font-medium hover:bg-accent"
          >
            <ArrowLeft aria-hidden className="size-3" />
            Back to Users
          </Link>
        }
      />
    </div>
  );
}

function UserDetailPage() {
  const { userId } = Route.useParams();
  // Loader throws notFound() for unknown IDs, so the record is guaranteed here.
  const user = getUser(userId) as UserRecord;
  const { admin } = useAdminAccess();
  const permissions = admin?.permissions ?? [];
  const session = useUserAdminSession(user.id, {
    name: admin?.name ?? "Kairo Operator",
    role: admin?.role ?? "Admin",
  });

  const effectiveStatus: UserAccountStatus = session.accountStatusOverride ?? user.accountStatus;

  const timeline = useMemo(() => {
    const noteEvents = session.notes.map((n) => ({
      id: n.id,
      at: n.at,
      kind: "admin_note" as const,
      summary: `${n.author} — ${n.body.slice(0, 80)}${n.body.length > 80 ? "…" : ""}`,
      sessionOnly: true,
      actor: n.author,
    }));
    return [...session.extraTimeline, ...noteEvents, ...user.activity].sort(
      (a, b) => new Date(b.at).getTime() - new Date(a.at).getTime(),
    );
  }, [session.extraTimeline, session.notes, user.activity]);

  const cases = useMemo(
    () => mockVerificationCases.filter((c) => c.candidateId === user.id),
    [user.id],
  );
  const activeCases = cases.filter(
    (c) => c.status !== "verified" && c.status !== "rejected" && c.status !== "unable_to_verify",
  );

  const [maskEmail, setMaskEmail] = useState(true);
  const [maskPhone, setMaskPhone] = useState(true);

  // Unsaved-changes guard on breadcrumb navigation.
  const router = useRouter();
  const [pendingLeaveHref, setPendingLeaveHref] = useState<string | null>(null);
  function tryNavigate(href: string) {
    if (session.hasSessionChanges) {
      setPendingLeaveHref(href);
    } else {
      router.navigate({ to: href });
    }
  }

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-4">
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb" className="text-xs text-muted-foreground">
        <ol className="flex items-center gap-1">
          <li>
            <button
              type="button"
              onClick={() => tryNavigate("/admin/users")}
              className="hover:text-foreground hover:underline"
            >
              Users
            </button>
          </li>
          <ChevronRight aria-hidden className="size-3" />
          <li className="font-medium text-foreground">{user.displayId}</li>
        </ol>
      </nav>

      {/* Header */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-foreground text-sm font-semibold text-background">
              {initialsFor(user)}
            </span>
            <div className="min-w-0">
              <h1 className="text-base font-semibold tracking-tight text-foreground">
                {user.fullName}
              </h1>
              <p className="text-xs text-muted-foreground">
                {user.displayId} · {PROFILE_TYPE_LABEL[user.profileType]} · {user.location}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <AccountBadge status={effectiveStatus} />
                <VerifiedChip label="Email" ok={user.emailVerified} />
                <VerifiedChip label="Phone" ok={user.phoneVerified} />
                <VerifiedChip label="Identity" ok={user.identityVerified} />
                <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                  Passport: {PASSPORT_STATUS_LABEL[user.passport.status]}
                </span>
                {user.attentionFlags.map((f) => (
                  <span
                    key={f}
                    className="inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-900 ring-1 ring-inset ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60"
                  >
                    <AlertTriangle aria-hidden className="size-3" />
                    {ATTENTION_LABEL[f]}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] md:grid-cols-4">
          <Field icon={<Mail className="size-3" />} label="Email">
            <button
              type="button"
              onClick={() => setMaskEmail((v) => !v)}
              className="font-mono text-foreground hover:underline"
              aria-label={maskEmail ? "Reveal email" : "Mask email"}
            >
              {maskEmail ? maskEmailAddr(user.email) : user.email}
            </button>
          </Field>
          <Field icon={<Phone className="size-3" />} label="Phone">
            <button
              type="button"
              onClick={() => setMaskPhone((v) => !v)}
              className="font-mono text-foreground hover:underline"
              aria-label={maskPhone ? "Reveal phone" : "Mask phone"}
            >
              {maskPhone ? maskPhoneNum(user.phone) : user.phone}
            </button>
          </Field>
          <Field icon={<MapPin className="size-3" />} label="Location">
            {user.location}
          </Field>
          <Field icon={<Fingerprint className="size-3" />} label="Passport ID">
            {user.passport.passportId ?? "—"}
          </Field>
          <Field label="Joined">{new Date(user.joinedAt).toLocaleDateString()}</Field>
          <Field label="Last active">{formatRelativeTime(user.lastActiveAt)}</Field>
          <Field label="Employer">{user.employer ?? "—"}</Field>
          <Field label="Institution">{user.educationInstitution ?? "—"}</Field>
        </div>
        {session.hasSessionChanges ? (
          <p className="mt-3 rounded bg-sky-50 px-2 py-1 text-[11px] text-sky-900 dark:bg-sky-950/40 dark:text-sky-200">
            Session-only workspace — changes are not saved to the backend and will be discarded on
            reload.
          </p>
        ) : null}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        {/* MAIN COLUMN */}
        <div className="flex min-w-0 flex-col gap-4">
          <OnboardingSection user={user} />
          <TrustPassportSection user={user} />
          <TrustScoreSection user={user} />
          <ActiveRequestsSection cases={activeCases} />
          <VerificationHistorySection user={user} />
          <CareerRecordsSection user={user} />
          <DocumentsSection user={user} />
          <SharingSection user={user} />
          <SecuritySection user={user} />
          <ActivityTimelineSection events={timeline} />
        </div>

        {/* SIDEBAR */}
        <aside className="flex flex-col gap-4">
          <AccountActionsPanel
            user={user}
            effectiveStatus={effectiveStatus}
            permissions={permissions}
            onAction={session.performAction}
            actionsTaken={session.actions}
          />
          <NotesPanel
            notes={session.notes}
            onAdd={session.addNote}
            author={admin?.name ?? "Kairo Operator"}
            role={admin?.role ?? "Admin"}
            canCreate={hasPermission(permissions, "users.notes.create")}
          />
        </aside>
      </div>

      <UnsavedChangesDialog
        open={pendingLeaveHref !== null}
        onOpenChange={(o) => {
          if (!o) setPendingLeaveHref(null);
        }}
        onConfirm={() => {
          const href = pendingLeaveHref;
          setPendingLeaveHref(null);
          if (href) router.navigate({ to: href });
        }}
        changes={sessionChangeSummary(session)}
      />
    </div>
  );
}

// ---------- Sections ----------

function OnboardingSection({ user }: { user: UserRecord }) {
  const o = user.onboarding;
  const currentIdx = ONBOARDING_STEP_ORDER.indexOf(o.currentStep);
  return (
    <WorkspaceSection
      title="Onboarding progress"
      description={`${o.profileCompletionPct}% complete · ${o.state.replace("_", " ")}`}
    >
      <ol className="mb-3 grid grid-cols-1 gap-1 md:grid-cols-7">
        {ONBOARDING_STEP_ORDER.map((step, i) => {
          const done = o.completedSteps.includes(step) || o.state === "completed";
          const isCurrent = step === o.currentStep && o.state !== "completed";
          const isBlocked = step === o.blockedStep;
          return (
            <li
              key={step}
              className={cn(
                "rounded-md border p-2 text-[11px]",
                isBlocked
                  ? "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200"
                  : done
                    ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200"
                    : isCurrent
                      ? "border-sky-300 bg-sky-50 text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200"
                      : "border-border bg-muted/40 text-muted-foreground",
              )}
            >
              <p className="font-medium">
                {i + 1}. {ONBOARDING_STEP_LABEL[step]}
              </p>
              {isBlocked ? (
                <p className="mt-0.5">Blocked</p>
              ) : done ? (
                <p className="mt-0.5">Complete</p>
              ) : isCurrent ? (
                <p className="mt-0.5">Current</p>
              ) : (
                <p className="mt-0.5">—</p>
              )}
            </li>
          );
        })}
      </ol>
      {o.blockedStep ? (
        <div
          role="alert"
          className="mb-2 rounded-md border border-rose-200 bg-rose-50 p-2 text-xs text-rose-900 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200"
        >
          <p className="font-medium">Blocked at {ONBOARDING_STEP_LABEL[o.blockedStep]}</p>
          <p>{o.blockedReason ?? "No reason recorded."}</p>
        </div>
      ) : null}
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-muted-foreground md:grid-cols-4">
        <div>
          <dt className="uppercase tracking-wide">Start method</dt>
          <dd className="text-foreground">{o.startMethod ?? "—"}</dd>
        </div>
        <div>
          <dt className="uppercase tracking-wide">Last activity</dt>
          <dd className="text-foreground">{formatRelativeTime(o.lastActivityAt)}</dd>
        </div>
        <div>
          <dt className="uppercase tracking-wide">Resume import</dt>
          <dd className="text-foreground">
            {o.resumeImport
              ? `${o.resumeImport.filename} (${o.resumeImport.parsedFields} fields, ${o.resumeImport.warnings} warnings)`
              : "—"}
          </dd>
        </div>
        <div>
          <dt className="uppercase tracking-wide">Current step</dt>
          <dd className="text-foreground">
            {currentIdx >= 0 ? ONBOARDING_STEP_LABEL[o.currentStep] : "—"}
          </dd>
        </div>
      </dl>
    </WorkspaceSection>
  );
}

function TrustPassportSection({ user }: { user: UserRecord }) {
  const p = user.passport;
  return (
    <WorkspaceSection
      title="Trust Passport"
      description={`${PASSPORT_STATUS_LABEL[p.status]} · updated ${formatRelativeTime(p.lastUpdatedAt)}`}
    >
      <div className="grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
        {Object.entries(p.sections).map(([k, v]) => (
          <div key={k} className="rounded-md border border-border bg-background p-2">
            <p className="uppercase tracking-wide text-muted-foreground">{k}</p>
            <p className="text-sm font-semibold text-foreground">{v}</p>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Public sharing:{" "}
        <span className="text-foreground">{p.publicShareEnabled ? "Enabled" : "Disabled"}</span>
      </p>
    </WorkspaceSection>
  );
}

function TrustScoreSection({ user }: { user: UserRecord }) {
  const s = user.trustScore;
  return (
    <WorkspaceSection
      title="Trust Score"
      description={`Mock data — not editable. Recalculated ${formatRelativeTime(s.lastRecalculatedAt)}.`}
    >
      <div className="flex flex-wrap items-baseline gap-4">
        <div>
          <p className="text-2xl font-semibold tabular-nums text-foreground">{s.current}</p>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
            {TRUST_BAND_LABEL[s.band]}
          </p>
        </div>
        <ul className="grid flex-1 grid-cols-2 gap-x-4 gap-y-0.5 text-[11px] text-muted-foreground md:grid-cols-4">
          <li>
            Verified: <span className="text-foreground">{s.verifiedSignals}</span>
          </li>
          <li>
            Pending: <span className="text-foreground">{s.pendingSignals}</span>
          </li>
          <li>
            Expired: <span className="text-foreground">{s.expiredSignals}</span>
          </li>
          <li>
            Deductions: <span className="text-foreground">−{s.riskDeductions}</span>
          </li>
        </ul>
      </div>
      {s.contributingFactors.length ? (
        <ul className="mt-3 list-inside list-disc space-y-0.5 text-[11px] text-muted-foreground">
          {s.contributingFactors.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      ) : null}
    </WorkspaceSection>
  );
}

function ActiveRequestsSection({ cases }: { cases: (typeof mockVerificationCases)[number][] }) {
  return (
    <WorkspaceSection title="Active verification requests" description={`${cases.length} open`}>
      {cases.length === 0 ? (
        <EmptyState title="No active requests" description="Nothing awaits action." />
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {cases.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-2 p-2 text-xs">
              <div className="min-w-0 flex-1">
                <Link
                  to="/admin/verifications/$caseId"
                  params={{ caseId: c.id }}
                  className="flex min-w-0 items-center gap-1 font-medium text-foreground hover:underline"
                >
                  {c.reference}
                  <ExternalLink aria-hidden className="size-3" />
                </Link>
                <p className="text-[11px] text-muted-foreground">
                  {c.organizationName} — {c.roleOrProgram}
                </p>
              </div>
              <StatusBadge status={c.status} />
              <PriorityBadge priority={c.priority} />
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {formatRelativeTime(c.updatedAt)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </WorkspaceSection>
  );
}

function VerificationHistorySection({ user }: { user: UserRecord }) {
  const rows = mockVerificationCases.filter((c) => c.candidateId === user.id);
  return (
    <WorkspaceSection
      title="Verification history"
      description={`${rows.length} record${rows.length === 1 ? "" : "s"}`}
    >
      {rows.length === 0 ? (
        <EmptyState title="No verification history" />
      ) : (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="min-w-full divide-y divide-border text-xs">
            <thead className="bg-muted/40 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-2 py-1.5">Case</th>
                <th className="px-2 py-1.5">Type</th>
                <th className="px-2 py-1.5">Organization</th>
                <th className="px-2 py-1.5">Status</th>
                <th className="px-2 py-1.5">Created</th>
                <th className="px-2 py-1.5">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-background">
              {rows.map((c) => (
                <tr key={c.id}>
                  <td className="px-2 py-1.5">
                    <Link
                      to="/admin/verifications/$caseId"
                      params={{ caseId: c.id }}
                      className="text-foreground hover:underline"
                    >
                      {c.reference}
                    </Link>
                  </td>
                  <td className="px-2 py-1.5 text-muted-foreground">{c.verificationType}</td>
                  <td className="px-2 py-1.5 text-muted-foreground">{c.organizationName}</td>
                  <td className="px-2 py-1.5">
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="px-2 py-1.5 tabular-nums text-muted-foreground">
                    {new Date(c.submittedAt).toLocaleDateString()}
                  </td>
                  <td className="px-2 py-1.5 tabular-nums text-muted-foreground">
                    {formatRelativeTime(c.updatedAt)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </WorkspaceSection>
  );
}

function CareerRecordsSection({ user }: { user: UserRecord }) {
  return (
    <WorkspaceSection
      title="Career & credential records"
      description={`${user.careerRecords.length} records`}
    >
      {user.careerRecords.length === 0 ? (
        <EmptyState
          title="No career records"
          description="This user has not added employment, education or certifications yet."
        />
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {user.careerRecords.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-2 p-2 text-xs">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-foreground">{r.title}</p>
                <p className="truncate text-[11px] text-muted-foreground">
                  {r.organization} · {r.kind} · {r.evidenceCount} evidence
                </p>
              </div>
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                {r.verificationStatus}
              </span>
              {r.relatedCaseId ? (
                <Link
                  to="/admin/verifications/$caseId"
                  params={{ caseId: r.relatedCaseId }}
                  className="text-[11px] text-foreground hover:underline"
                >
                  Case →
                </Link>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </WorkspaceSection>
  );
}

function DocumentsSection({ user }: { user: UserRecord }) {
  return (
    <WorkspaceSection title="Documents" description={`${user.documents.length} uploaded`}>
      {user.documents.length === 0 ? (
        <EmptyState title="No documents" />
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {user.documents.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center gap-2 p-2 text-xs">
              <FileText aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-foreground">{d.type}</p>
                <p className="truncate text-[11px] text-muted-foreground">{d.relatedClaim}</p>
              </div>
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                {d.reviewStatus}
              </span>
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {formatRelativeTime(d.uploadedAt)}
              </span>
              {d.relatedCaseId ? (
                <Link
                  to="/admin/verifications/$caseId"
                  params={{ caseId: d.relatedCaseId }}
                  className="text-[11px] text-foreground hover:underline"
                >
                  Case →
                </Link>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </WorkspaceSection>
  );
}

function SharingSection({ user }: { user: UserRecord }) {
  return (
    <WorkspaceSection
      title="Passport sharing"
      description={`${user.shares.length} link${user.shares.length === 1 ? "" : "s"}`}
    >
      {user.shares.length === 0 ? (
        <EmptyState
          title="No share activity"
          description="This user has not created any Trust Passport shares."
        />
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {user.shares.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-2 p-2 text-xs">
              <Share2 aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-foreground">{s.label}</p>
                <p className="truncate text-[11px] text-muted-foreground">
                  {s.scope} · created {formatRelativeTime(s.createdAt)}
                </p>
              </div>
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                {s.status}
              </span>
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {s.viewCount} views
              </span>
            </li>
          ))}
        </ul>
      )}
    </WorkspaceSection>
  );
}

function SecuritySection({ user }: { user: UserRecord }) {
  return (
    <WorkspaceSection
      title="Security & account activity"
      description={`${user.security.length} recent events`}
    >
      {user.security.length === 0 ? (
        <EmptyState title="No security events" />
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {user.security.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center gap-2 p-2 text-xs">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-foreground">{e.summary}</p>
                <p className="truncate text-[11px] text-muted-foreground">
                  {e.deviceCategory} · {e.approximateLocation}
                </p>
              </div>
              <span
                className={cn(
                  "rounded px-1.5 py-0.5 text-[10px] font-medium",
                  e.outcome === "success"
                    ? "bg-emerald-50 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200"
                    : e.outcome === "failed"
                      ? "bg-rose-50 text-rose-900 dark:bg-rose-950/40 dark:text-rose-200"
                      : "bg-muted text-muted-foreground",
                )}
              >
                {e.outcome}
              </span>
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {formatRelativeTime(e.at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </WorkspaceSection>
  );
}

function ActivityTimelineSection({
  events,
}: {
  events: Array<{
    id: string;
    at: string;
    kind: string;
    summary: string;
    sessionOnly?: boolean;
    actor?: string;
  }>;
}) {
  return (
    <WorkspaceSection title="Activity timeline" description={`${events.length} events`}>
      {events.length === 0 ? (
        <EmptyState title="No activity yet" />
      ) : (
        <ol className="relative space-y-2 border-l border-border pl-4">
          {events.map((e) => (
            <li key={e.id} className="relative">
              <span
                aria-hidden
                className={cn(
                  "absolute -left-[19px] top-1.5 size-2 rounded-full ring-2 ring-background",
                  e.sessionOnly ? "bg-sky-500" : "bg-muted-foreground/50",
                )}
              />
              <div className="text-xs">
                <p className="text-foreground">{e.summary}</p>
                <p className="text-[11px] text-muted-foreground">
                  {formatRelativeTime(e.at)}
                  {e.actor ? ` · ${e.actor}` : ""}
                  {e.sessionOnly ? " · Session-only" : ""}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </WorkspaceSection>
  );
}

// ---------- Sidebar panels ----------

interface AccountActionSpec {
  kind: UserAdminActionKind;
  label: string;
  helper: string;
  permission: WorkflowPermission;
  destructive?: boolean;
  needsReason?: boolean;
  availableWhen?: (status: UserAccountStatus) => boolean;
}

const ACCOUNT_ACTIONS: AccountActionSpec[] = [
  {
    kind: "password_reset_prepared",
    label: "Send password reset",
    helper: "Simulates sending a reset email to the user.",
    permission: "users.password_reset.prepare",
  },
  {
    kind: "email_verification_resent",
    label: "Resend email verification",
    helper: "Simulates re-sending the verification email.",
    permission: "users.verification.resend",
  },
  {
    kind: "phone_verification_resent",
    label: "Resend phone verification",
    helper: "Simulates re-sending an SMS code.",
    permission: "users.verification.resend",
  },
  {
    kind: "sessions_revoked",
    label: "Revoke active sessions",
    helper: "Simulates signing the user out of all devices.",
    permission: "users.sessions.revoke",
    needsReason: true,
  },
  {
    kind: "flagged_for_trust_safety",
    label: "Flag for Trust & Safety",
    helper: "Simulates adding a risk flag for review.",
    permission: "users.risk.flag",
    needsReason: true,
  },
  {
    kind: "account_disabled",
    label: "Disable account",
    helper: "Simulates blocking sign-in.",
    permission: "users.account.disable",
    destructive: true,
    needsReason: true,
    availableWhen: (s) => s !== "disabled",
  },
  {
    kind: "account_reenabled",
    label: "Re-enable account",
    helper: "Simulates restoring sign-in.",
    permission: "users.account.enable",
    availableWhen: (s) => s === "disabled" || s === "suspended",
  },
  {
    kind: "data_export_prepared",
    label: "Prepare data export",
    helper: "Simulates staging a user data export.",
    permission: "users.data_export.prepare",
  },
  {
    kind: "deletion_prepared",
    label: "Prepare deletion request",
    helper: "Simulates opening a deletion request. No data is deleted.",
    permission: "users.deletion.prepare",
    destructive: true,
    needsReason: true,
  },
];

function AccountActionsPanel({
  user,
  effectiveStatus,
  permissions,
  onAction,
  actionsTaken,
}: {
  user: UserRecord;
  effectiveStatus: UserAccountStatus;
  permissions: WorkflowPermission[];
  onAction: (kind: UserAdminActionKind, opts?: { reason?: string; impactSummary?: string }) => void;
  actionsTaken: { id: string; kind: UserAdminActionKind; at: string }[];
}) {
  const [pending, setPending] = useState<AccountActionSpec | null>(null);
  const [reason, setReason] = useState("");

  return (
    <WorkspaceSection
      title="Account actions"
      description="All actions are simulated and session-only."
    >
      <ul className="flex flex-col gap-1.5">
        {ACCOUNT_ACTIONS.map((a) => {
          const allowed = hasPermission(permissions, a.permission);
          const available = a.availableWhen ? a.availableWhen(effectiveStatus) : true;
          const disabled = !allowed || !available;
          return (
            <li key={a.kind}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => {
                  setReason("");
                  setPending(a);
                }}
                className={cn(
                  "flex w-full items-start justify-between gap-2 rounded-md border border-border bg-background px-2 py-1.5 text-left text-xs hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50",
                  a.destructive && !disabled && "hover:border-destructive/40",
                )}
                aria-label={a.label}
                title={
                  !allowed
                    ? "You do not have permission for this action."
                    : !available
                      ? "Not available for the current account status."
                      : a.helper
                }
              >
                <span className="min-w-0">
                  <span
                    className={cn(
                      "block font-medium",
                      a.destructive ? "text-destructive" : "text-foreground",
                    )}
                  >
                    {a.label}
                  </span>
                  <span className="block text-[11px] text-muted-foreground">{a.helper}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {actionsTaken.length > 0 ? (
        <div className="mt-3">
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            This session
          </p>
          <ul className="mt-1 space-y-0.5 text-[11px] text-muted-foreground">
            {actionsTaken.map((a) => (
              <li key={a.id}>
                <span className="text-foreground">{USER_ACTION_LABEL[a.kind]}</span> ·{" "}
                {formatRelativeTime(a.at)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <AlertDialog
        open={pending !== null}
        onOpenChange={(o) => {
          if (!o) setPending(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className={cn(pending?.destructive && "text-destructive")}>
              {pending?.label}
            </AlertDialogTitle>
            <AlertDialogDescription>
              This is a simulated action. No email, SMS or account change will actually occur. It is
              recorded in the session timeline for{" "}
              <span className="font-medium text-foreground">{user.fullName}</span>.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {pending?.needsReason ? (
            <div className="grid gap-1">
              <label
                htmlFor="action-reason"
                className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground"
              >
                Reason <span className="text-destructive">*</span>
              </label>
              <textarea
                id="action-reason"
                rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Why is this action needed?"
                className="rounded-md border border-border bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
          ) : null}
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={pending?.needsReason ? reason.trim().length < 3 : false}
              className={cn(
                pending?.destructive &&
                  "bg-destructive text-destructive-foreground hover:bg-destructive/90",
              )}
              onClick={() => {
                if (!pending) return;
                onAction(pending.kind, {
                  reason: pending.needsReason ? reason.trim() : undefined,
                  impactSummary: pending.helper,
                });
                setPending(null);
                setReason("");
              }}
            >
              Confirm (simulated)
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </WorkspaceSection>
  );
}

function NotesPanel({
  notes,
  onAdd,
  author,
  role,
  canCreate,
}: {
  notes: {
    id: string;
    at: string;
    author: string;
    role: string;
    category: UserNoteCategory;
    body: string;
  }[];
  onAdd: (body: string, category: UserNoteCategory) => void;
  author: string;
  role: string;
  canCreate: boolean;
}) {
  const [body, setBody] = useState("");
  const [category, setCategory] = useState<UserNoteCategory>("general");

  return (
    <WorkspaceSection title="Internal notes" description="Session-only. Not visible to the user.">
      {canCreate ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!body.trim()) return;
            onAdd(body, category);
            setBody("");
            setCategory("general");
          }}
          className="rounded-md border border-border bg-background p-2"
        >
          <label htmlFor="user-note-body" className="sr-only">
            Internal note
          </label>
          <textarea
            id="user-note-body"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder={`Add a note as ${author}. Never visible to the user.`}
            rows={3}
            className="block w-full resize-y rounded border border-border bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <div className="mt-2 flex items-center justify-between gap-2">
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as UserNoteCategory)}
              className="h-7 rounded border border-border bg-background px-1.5 text-xs"
              aria-label="Note category"
            >
              {Object.entries(USER_NOTE_CATEGORY_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
            <button
              type="submit"
              disabled={!body.trim()}
              className="inline-flex h-7 items-center gap-1 rounded-md bg-foreground px-2 text-xs font-medium text-background hover:bg-foreground/90 disabled:opacity-50"
            >
              <StickyNote aria-hidden className="size-3" />
              Add note
            </button>
          </div>
        </form>
      ) : (
        <p className="rounded-md border border-dashed border-border p-2 text-[11px] text-muted-foreground">
          You do not have permission to add internal notes on this user.
        </p>
      )}

      {notes.length === 0 ? (
        <p className="mt-3 text-[11px] text-muted-foreground">No internal notes yet.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {notes.map((n) => (
            <li key={n.id} className="rounded-md border border-border bg-background p-2">
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-xs font-medium text-foreground">
                  {n.author} <span className="font-normal text-muted-foreground">· {n.role}</span>
                </p>
                <p className="text-[10px] tabular-nums text-muted-foreground">
                  {formatRelativeTime(n.at)}
                </p>
              </div>
              <p className="mt-1 whitespace-pre-wrap text-xs">{n.body}</p>
              <div className="mt-1 flex flex-wrap items-center gap-1">
                <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                  {USER_NOTE_CATEGORY_LABEL[n.category]}
                </span>
                <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-700 dark:bg-sky-950/40 dark:text-sky-300">
                  Session-only
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
      {/* Reference kept role for future avatar rendering */}
      <span className="sr-only">Author role: {role}</span>
    </WorkspaceSection>
  );
}

// ---------- Small UI helpers ----------

function Field({
  icon,
  label,
  children,
}: {
  icon?: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="flex items-center gap-1 uppercase tracking-wide text-muted-foreground">
        {icon}
        {label}
      </p>
      <p className="mt-0.5 text-xs text-foreground">{children}</p>
    </div>
  );
}

function AccountBadge({ status }: { status: UserAccountStatus }) {
  const map: Record<UserAccountStatus, string> = {
    active:
      "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60",
    pending:
      "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-900/60",
    disabled:
      "bg-zinc-100 text-zinc-800 ring-zinc-200 dark:bg-zinc-800/60 dark:text-zinc-200 dark:ring-zinc-700",
    suspended:
      "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-900/60",
    deletion_requested:
      "bg-orange-50 text-orange-900 ring-orange-200 dark:bg-orange-950/40 dark:text-orange-200 dark:ring-orange-900/60",
  };
  return (
    <span
      className={
        "inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset " +
        map[status]
      }
    >
      {ACCOUNT_STATUS_LABEL[status]}
    </span>
  );
}

function VerifiedChip({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset",
        ok
          ? "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-900/60"
          : "bg-muted text-muted-foreground ring-border",
      )}
    >
      {ok ? <ShieldCheck aria-hidden className="size-3" /> : null}
      {label}
    </span>
  );
}

function maskEmailAddr(e: string): string {
  const [name, domain] = e.split("@");
  if (!domain) return e;
  const shown = name.slice(0, 2);
  return `${shown}${"*".repeat(Math.max(0, name.length - 2))}@${domain}`;
}
function maskPhoneNum(p: string): string {
  if (p.length < 4) return p;
  return `${p.slice(0, 3)} ${"•".repeat(Math.max(0, p.length - 6))} ${p.slice(-2)}`;
}

function sessionChangeSummary(s: ReturnType<typeof useUserAdminSession>): string[] {
  const out: string[] = [];
  if (s.notes.length) out.push(`${s.notes.length} internal note${s.notes.length === 1 ? "" : "s"}`);
  if (s.actions.length)
    out.push(`${s.actions.length} simulated action${s.actions.length === 1 ? "" : "s"}`);
  if (s.accountStatusOverride) out.push(`Account status changed to ${s.accountStatusOverride}`);
  if (s.addedRiskFlags.length) out.push(`${s.addedRiskFlags.length} risk flag added`);
  return out;
}

// Silence unused imports needed for future use.
void UsersIcon;
