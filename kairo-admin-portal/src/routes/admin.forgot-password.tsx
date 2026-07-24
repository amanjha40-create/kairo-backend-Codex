import { useState, type FormEvent } from "react";
import { Link, createFileRoute } from "@tanstack/react-router";
import { ArrowLeft, CheckCircle2, Loader2, Mail } from "lucide-react";
import { AdminEnvironmentNotice } from "@/features/admin/components/admin-environment-notice";
import { useAdminAuth } from "@/features/admin/auth/admin-auth";
import { KairoLogo } from "@/features/branding/kairo-logo";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin/forgot-password")({
  head: () => ({
    meta: [
      { title: "Reset access — Kairo Operations" },
      { name: "description", content: "Request an admin password reset for Kairo Operations." },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: ForgotPasswordPage,
});

function ForgotPasswordPage() {
  const auth = useAdminAuth();
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setError("Enter a valid email address.");
      return;
    }
    setSubmitting(true);
    const result = await auth.forgotPassword(email);
    setSubmitting(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setSubmitted(true);
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-white">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(1000px 600px at 90% -10%, rgba(15,168,165,0.12), transparent 60%), radial-gradient(900px 500px at -10% 110%, rgba(11,37,69,0.10), transparent 55%)",
        }}
      />
      <main className="relative mx-auto flex min-h-screen max-w-md flex-col justify-center px-5 py-10 sm:px-6">
        <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-6 shadow-[0_20px_60px_-30px_rgba(11,37,69,0.30)] backdrop-blur sm:p-8">
          <div className="flex flex-col items-center text-center">
            <KairoLogo width={150} />
            <h1 className="mt-5 text-xl font-semibold tracking-tight text-slate-900">
              Kairo Operations
            </h1>
            <p className="mt-1 text-sm text-slate-500">Reset your admin access</p>
          </div>

          <div className="mt-6">
            <AdminEnvironmentNotice />
          </div>

          {submitted ? (
            <div className="mt-7 rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
              <div className="flex items-start gap-2">
                <CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0" />
                <p>
                  If an authorised Admin account exists for this email, password reset instructions
                  will be sent.
                </p>
              </div>
              <p className="mt-3 text-xs text-emerald-700/80">
                This is a simulated frontend flow — no email is actually delivered in this
                environment.
              </p>
            </div>
          ) : (
            <form onSubmit={onSubmit} noValidate className="mt-7 space-y-4">
              <div>
                <label htmlFor="email" className="mb-1 block text-xs font-medium text-slate-700">
                  Work email
                </label>
                <div className="relative">
                  <Mail
                    aria-hidden
                    className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400"
                  />
                  <input
                    id="email"
                    type="email"
                    disabled={!auth.isConfigured && auth.mode === "production"}
                    autoComplete="username"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      if (error) setError(null);
                    }}
                    aria-invalid={!!error}
                    aria-describedby={error ? "email-error" : undefined}
                    className={cn(
                      "h-10 w-full rounded-md border bg-white pl-9 pr-3 text-sm text-slate-900 placeholder:text-slate-400",
                      "focus:outline-none focus:ring-2 focus:ring-offset-1",
                      error
                        ? "border-rose-400 focus:border-rose-500 focus:ring-rose-200"
                        : "border-slate-300 focus:border-[#0FA8A5] focus:ring-[#0FA8A5]/30",
                    )}
                    placeholder="you@kairo.internal"
                  />
                </div>
                {error ? (
                  <p id="email-error" role="alert" className="mt-1 text-xs text-rose-600">
                    {error}
                  </p>
                ) : null}
              </div>

              <button
                type="submit"
                disabled={submitting || (!auth.isConfigured && auth.mode === "production")}
                className={cn(
                  "flex h-10 w-full items-center justify-center gap-2 rounded-md text-sm font-semibold text-white transition-colors",
                  "bg-[#0B2545] hover:bg-[#0B2545]/92 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0FA8A5] focus-visible:ring-offset-2",
                  submitting && "cursor-not-allowed opacity-80",
                )}
              >
                {submitting ? (
                  <>
                    <Loader2 aria-hidden className="size-4 animate-spin" />
                    Requesting…
                  </>
                ) : !auth.isConfigured && auth.mode === "production" ? (
                  "Reset unavailable"
                ) : (
                  "Request reset link"
                )}
              </button>
            </form>
          )}

          <div className="mt-6 border-t border-slate-100 pt-4">
            <Link
              to="/admin/login"
              search={{ redirect: undefined }}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-[#0B2545] hover:underline"
            >
              <ArrowLeft aria-hidden className="size-3.5" />
              Back to sign in
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
