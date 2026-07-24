/**
 * ContactReviewDialog — review or add a verification contact for a case.
 *
 * Session-only. Approving / rejecting toggles the contact's session
 * eligibility; adding a new contact appends a session-only contact record
 * that the outreach preparation flow can select. Nothing is persisted.
 */
import { useState } from "react";
import { z } from "zod";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { VerificationContact } from "@/features/admin/data/cases";
import { CONTACT_SOURCE_LABEL, CONTACT_STATE_LABEL } from "@/features/admin/data/cases";
import type { UseOutreachSessionResult } from "@/features/admin/workflow/use-outreach-session";

type Mode =
  { kind: "review"; contact: VerificationContact } | { kind: "add"; organization: string };

const emailSchema = z.string().trim().email({ message: "Enter a valid email address." }).max(255);
const nameSchema = z.string().trim().min(2, { message: "Name is required." }).max(120);
const roleSchema = z.string().trim().min(2, { message: "Role is required." }).max(120);

export function ContactReviewDialog({
  open,
  onOpenChange,
  mode,
  outreach,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  mode: Mode | null;
  outreach: UseOutreachSessionResult;
}) {
  const [reviewReason, setReviewReason] = useState("");
  const [draftName, setDraftName] = useState("");
  const [draftRole, setDraftRole] = useState("");
  const [draftEmail, setDraftEmail] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  function reset() {
    setReviewReason("");
    setDraftName("");
    setDraftRole("");
    setDraftEmail("");
    setErrors({});
  }

  function handleApprove() {
    if (mode?.kind !== "review") return;
    outreach.approveContact(mode.contact.id, mode.contact.name);
    toast(`${mode.contact.name} approved`, {
      description: "Session-only. Available for outreach.",
    });
    onOpenChange(false);
    reset();
  }

  function handleReject() {
    if (mode?.kind !== "review") return;
    if (!reviewReason.trim()) {
      setErrors({ reason: "Enter a short reason so the timeline reflects the decision." });
      return;
    }
    outreach.rejectContact(mode.contact.id, mode.contact.name, reviewReason.trim());
    toast(`${mode.contact.name} rejected`, { description: "Session-only." });
    onOpenChange(false);
    reset();
  }

  function handleAdd() {
    if (mode?.kind !== "add") return;
    const parsed = z
      .object({ name: nameSchema, role: roleSchema, email: emailSchema })
      .safeParse({ name: draftName, role: draftRole, email: draftEmail });
    if (!parsed.success) {
      const map: Record<string, string> = {};
      for (const issue of parsed.error.issues) {
        const key = issue.path[0]?.toString();
        if (key) map[key] = issue.message;
      }
      setErrors(map);
      return;
    }
    const [local, domain] = parsed.data.email.split("@");
    const shown = local.slice(0, 1);
    const rest = local.length > 1 ? "•".repeat(Math.max(2, local.length - 1)) : "";
    const emailMasked = `${shown}${rest}@${domain}`;
    outreach.addContact({
      name: parsed.data.name,
      role: parsed.data.role,
      organization: mode.organization,
      emailMasked,
      source: "manual_admin_entry",
      state: "unverified",
      confidence: 0.6,
      bounceCount: 0,
      outreachEligible: false,
      internalApprovalStatus: "pending",
    });
    toast("Contact added", { description: "Session-only. Review to approve for outreach." });
    onOpenChange(false);
    reset();
  }

  const isReview = mode?.kind === "review";
  const isAdd = mode?.kind === "add";

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        if (!v) reset();
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isReview ? "Review contact" : "Add contact"}</DialogTitle>
          <DialogDescription>
            {isReview
              ? "Approve for outreach or reject with a reason. Session-only."
              : "Add a verification contact for this case. Session-only until the registry integration lands."}
          </DialogDescription>
        </DialogHeader>

        {isReview && mode ? (
          <div className="space-y-4">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-md border border-border bg-muted/30 p-3 text-xs">
              <dt className="text-muted-foreground">Name</dt>
              <dd className="text-foreground">{mode.contact.name}</dd>
              <dt className="text-muted-foreground">Role</dt>
              <dd className="text-foreground">{mode.contact.role}</dd>
              <dt className="text-muted-foreground">Email</dt>
              <dd className="font-mono text-foreground">{mode.contact.emailMasked}</dd>
              <dt className="text-muted-foreground">Source</dt>
              <dd className="text-foreground">{CONTACT_SOURCE_LABEL[mode.contact.source]}</dd>
              <dt className="text-muted-foreground">Current state</dt>
              <dd className="text-foreground">{CONTACT_STATE_LABEL[mode.contact.state]}</dd>
              <dt className="text-muted-foreground">Confidence</dt>
              <dd className="text-foreground">{Math.round(mode.contact.confidence * 100)}%</dd>
            </dl>
            <div>
              <label htmlFor="reject-reason" className="block text-xs font-medium text-foreground">
                Rejection reason (required to reject)
              </label>
              <textarea
                id="reject-reason"
                value={reviewReason}
                onChange={(e) => setReviewReason(e.target.value)}
                rows={3}
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                placeholder="e.g. Address bounced twice in the past 30 days."
              />
              {errors.reason ? (
                <p className="mt-1 text-[11px] text-destructive">{errors.reason}</p>
              ) : null}
            </div>
          </div>
        ) : null}

        {isAdd && mode ? (
          <div className="space-y-3">
            <Field
              id="c-name"
              label="Name"
              value={draftName}
              onChange={setDraftName}
              error={errors.name}
              placeholder="Full name"
            />
            <Field
              id="c-role"
              label="Role at organization"
              value={draftRole}
              onChange={setDraftRole}
              error={errors.role}
              placeholder="e.g. HR Manager"
            />
            <Field
              id="c-email"
              label="Email"
              value={draftEmail}
              onChange={setDraftEmail}
              error={errors.email}
              placeholder="name@company.example"
              type="email"
            />
            <p className="rounded-md bg-muted/50 px-2 py-1.5 text-[11px] text-muted-foreground">
              Organization: <span className="text-foreground">{mode.organization}</span>. The
              contact will be created as <em>Unverified</em> and must be approved before outreach.
            </p>
          </div>
        ) : null}

        <DialogFooter>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="h-8 rounded-md border border-border bg-background px-3 text-xs text-foreground hover:bg-accent"
          >
            Cancel
          </button>
          {isReview ? (
            <>
              <button
                type="button"
                onClick={handleReject}
                className="h-8 rounded-md border border-destructive/40 bg-background px-3 text-xs font-medium text-destructive hover:bg-destructive/10"
              >
                Reject
              </button>
              <button
                type="button"
                onClick={handleApprove}
                className="h-8 rounded-md bg-emerald-600 px-3 text-xs font-medium text-white hover:bg-emerald-700"
              >
                Approve for outreach
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={handleAdd}
              className="h-8 rounded-md bg-foreground px-3 text-xs font-medium text-background hover:bg-foreground/90"
            >
              Add contact
            </button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  error,
  placeholder,
  type = "text",
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  error?: string;
  placeholder?: string;
  type?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-foreground">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
      />
      {error ? <p className="mt-1 text-[11px] text-destructive">{error}</p> : null}
    </div>
  );
}
