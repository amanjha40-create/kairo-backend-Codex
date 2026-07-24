import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  CheckCircle2,
  FileEdit,
  Mail,
  MailWarning,
  RefreshCw,
  Send,
  ShieldCheck,
  UserPlus,
  Building2,
} from "lucide-react";
import { formatRelativeTime } from "../lib/format";
import type { AdminActivity, AdminActivityKind } from "../data/types";

const ICONS: Record<AdminActivityKind, { Icon: typeof CheckCircle2; tone: string }> = {
  user_registered: { Icon: UserPlus, tone: "text-sky-600 dark:text-sky-400" },
  verification_submitted: { Icon: Send, tone: "text-indigo-600 dark:text-indigo-400" },
  correction_requested: { Icon: FileEdit, tone: "text-amber-600 dark:text-amber-400" },
  resubmitted: { Icon: RefreshCw, tone: "text-sky-600 dark:text-sky-400" },
  organization_resolved: { Icon: Building2, tone: "text-violet-600 dark:text-violet-400" },
  employer_outreach_sent: { Icon: Mail, tone: "text-muted-foreground" },
  employer_responded: { Icon: CheckCircle2, tone: "text-emerald-600 dark:text-emerald-400" },
  verification_approved: { Icon: ShieldCheck, tone: "text-emerald-600 dark:text-emerald-400" },
  email_delivery_failed: { Icon: MailWarning, tone: "text-rose-600 dark:text-rose-400" },
  trust_passport_updated: { Icon: AlertTriangle, tone: "text-muted-foreground" },
};

export function ActivityItem({ item }: { item: AdminActivity }) {
  const { Icon, tone } = ICONS[item.kind];
  return (
    <li className="flex items-start gap-3 py-2.5">
      <span
        className={`mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-muted ${tone}`}
      >
        <Icon aria-hidden className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-foreground">
          <span className="font-medium">{item.actor}</span>{" "}
          <span className="text-muted-foreground">{item.action}</span>
          {item.subject ? (
            <>
              {" "}
              <span className="font-medium">{item.subject}</span>
            </>
          ) : null}
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          <span className="capitalize">{item.actorRole}</span>
          <span className="mx-1.5 text-border">·</span>
          <time dateTime={item.timestamp}>{formatRelativeTime(item.timestamp)}</time>
        </p>
      </div>
      <Link
        to={item.detailHref}
        className="shrink-0 self-center text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
      >
        View
      </Link>
    </li>
  );
}
