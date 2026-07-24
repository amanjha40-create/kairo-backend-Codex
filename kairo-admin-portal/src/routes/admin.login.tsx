import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, createFileRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { AlertCircle, Eye, EyeOff, Loader2, Lock, Mail, ShieldCheck } from "lucide-react";
import { z } from "zod";
import { AdminEnvironmentNotice } from "@/features/admin/components/admin-environment-notice";
import { KairoLogo } from "@/features/branding/kairo-logo";
import { isSafeAdminRedirect, normalizeAdminRedirect } from "@/features/admin/auth/redirects";
import { useAdminAuth } from "@/features/admin/auth/admin-auth";
import { cn } from "@/lib/utils";

const searchSchema = z.object({
  redirect: z.string().optional(),
});

export const Route = createFileRoute("/admin/login")({
  head: () => ({
    meta: [
      { title: "Sign in — Kairo Operations" },
      { name: "description", content: "Secure sign-in for authorised Kairo operators." },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  validateSearch: (search) => {
    const parsed = searchSchema.parse(search);
    return {
      redirect: isSafeAdminRedirect(parsed.redirect) ? parsed.redirect : undefined,
    };
  },
  component: AdminLoginPage,
});

function AdminLoginPage() {
  const auth = useAdminAuth();
  const navigate = useNavigate();
  const search = useSearch({ from: "/admin/login" });

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});

  const emailValid = useMemo(() => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()), [email]);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setFormError(null);
    const errs: typeof fieldErrors = {};
    if (!email.trim()) errs.email = "Enter your Kairo email.";
    else if (!emailValid) errs.email = "Enter a valid email address.";
    if (!password) errs.password = "Enter your password.";
    setFieldErrors(errs);
    if (Object.keys(errs).length > 0) return;

    setSubmitting(true);
    const result = await auth.login(email, password, remember);
    setSubmitting(false);
    if (!result.ok) {
      setFormError(result.error);
      return;
    }
    const target = normalizeAdminRedirect(search.redirect);
    navigate({ to: target, replace: true });
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-white">
      {/* Ambient Kairo brand background */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(1000px 600px at 90% -10%, rgba(15,168,165,0.12), transparent 60%), radial-gradient(900px 500px at -10% 110%, rgba(11,37,69,0.10), transparent 55%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-px"
        style={{
          background: "linear-gradient(90deg, transparent, rgba(15,168,165,0.5), transparent)",
        }}
      />

      <main className="relative mx-auto flex min-h-screen max-w-md flex-col justify-center px-5 py-10 sm:px-6">
        <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-6 shadow-[0_20px_60px_-30px_rgba(11,37,69,0.30)] backdrop-blur sm:p-8">
          <div className="flex flex-col items-center text-center">
            <KairoLogo width={150} />
            <h1 className="mt-5 text-xl font-semibold tracking-tight text-slate-900">
              Kairo Operations
            </h1>
            <p className="mt-1 text-sm text-slate-500">Internal Trust Infrastructure</p>
            <p className="mt-3 text-xs text-slate-500">
              Secure access for authorised Kairo operators.
            </p>
          </div>

          <div className="mt-6">
            <AdminEnvironmentNotice showDemoCredentials />
          </div>

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
                  inputMode="email"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    if (fieldErrors.email) setFieldErrors((f) => ({ ...f, email: undefined }));
                    if (formError) setFormError(null);
                  }}
                  aria-invalid={!!fieldErrors.email}
                  aria-describedby={fieldErrors.email ? "email-error" : undefined}
                  className={cn(
                    "h-10 w-full rounded-md border bg-white pl-9 pr-3 text-sm text-slate-900 placeholder:text-slate-400",
                    "focus:outline-none focus:ring-2 focus:ring-offset-1",
                    fieldErrors.email
                      ? "border-rose-400 focus:border-rose-500 focus:ring-rose-200"
                      : "border-slate-300 focus:border-[#0FA8A5] focus:ring-[#0FA8A5]/30",
                  )}
                  placeholder="you@kairo.internal"
                />
              </div>
              {fieldErrors.email ? (
                <p id="email-error" role="alert" className="mt-1 text-xs text-rose-600">
                  {fieldErrors.email}
                </p>
              ) : null}
            </div>

            <div>
              <div className="mb-1 flex items-center justify-between">
                <label htmlFor="password" className="block text-xs font-medium text-slate-700">
                  Password
                </label>
                <Link
                  to="/admin/forgot-password"
                  className="text-xs font-medium text-[#0B2545] underline-offset-2 hover:underline"
                >
                  Forgot password?
                </Link>
              </div>
              <div className="relative">
                <Lock
                  aria-hidden
                  className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400"
                />
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  disabled={!auth.isConfigured && auth.mode === "production"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    if (fieldErrors.password)
                      setFieldErrors((f) => ({ ...f, password: undefined }));
                    if (formError) setFormError(null);
                  }}
                  onKeyUp={(e) => setCapsLock(e.getModifierState && e.getModifierState("CapsLock"))}
                  onKeyDown={(e) =>
                    setCapsLock(e.getModifierState && e.getModifierState("CapsLock"))
                  }
                  aria-invalid={!!fieldErrors.password}
                  aria-describedby={
                    fieldErrors.password ? "password-error" : capsLock ? "caps-hint" : undefined
                  }
                  className={cn(
                    "h-10 w-full rounded-md border bg-white pl-9 pr-10 text-sm text-slate-900 placeholder:text-slate-400",
                    "focus:outline-none focus:ring-2 focus:ring-offset-1",
                    fieldErrors.password
                      ? "border-rose-400 focus:border-rose-500 focus:ring-rose-200"
                      : "border-slate-300 focus:border-[#0FA8A5] focus:ring-[#0FA8A5]/30",
                  )}
                  placeholder="Enter your password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((s) => !s)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-[#0FA8A5]/40"
                >
                  {showPassword ? (
                    <EyeOff aria-hidden className="size-4" />
                  ) : (
                    <Eye aria-hidden className="size-4" />
                  )}
                </button>
              </div>
              {fieldErrors.password ? (
                <p id="password-error" role="alert" className="mt-1 text-xs text-rose-600">
                  {fieldErrors.password}
                </p>
              ) : capsLock ? (
                <p id="caps-hint" className="mt-1 text-xs text-amber-600">
                  Caps Lock is on.
                </p>
              ) : null}
            </div>

            <label className="flex cursor-pointer select-none items-center gap-2 text-xs text-slate-600">
              <input
                type="checkbox"
                checked={remember}
                disabled={!auth.isConfigured && auth.mode === "production"}
                onChange={(e) => setRemember(e.target.checked)}
                className="size-3.5 rounded border-slate-300 text-[#0B2545] focus:ring-[#0FA8A5]/40"
              />
              Remember this device
            </label>

            {formError ? (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-md border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-700"
              >
                <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
                <span>{formError}</span>
              </div>
            ) : null}

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
                  Signing in…
                </>
              ) : !auth.isConfigured && auth.mode === "production" ? (
                "Authentication unavailable"
              ) : (
                "Sign in"
              )}
            </button>
          </form>

          <div className="mt-6 flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 p-2.5 text-[11px] text-slate-500">
            <ShieldCheck aria-hidden className="size-3.5 text-[#0FA8A5]" />
            <span>
              {auth.mode === "demo"
                ? "Demo mode only. Authentication and permissions are simulated in the browser."
                : "Secure internal access only. Authorised Kairo personnel only."}
            </span>
          </div>
        </div>

        <p className="mt-4 text-center text-[11px] text-slate-400">© Kairo — Operations Portal</p>
      </main>
      <PostAuthGuard />
    </div>
  );
}

/**
 * If the user is already authenticated when they land on /admin/login,
 * the parent AdminRouter effect redirects them — this guard just prevents
 * a rendered flash of the form in the same tick.
 */
function PostAuthGuard() {
  const auth = useAdminAuth();
  const navigate = useNavigate();
  const search = useSearch({ from: "/admin/login" });
  useEffect(() => {
    if (auth.status === "authenticated") {
      const target = normalizeAdminRedirect(search.redirect);
      navigate({ to: target, replace: true });
    }
  }, [auth.status, navigate, search.redirect]);
  return null;
}
