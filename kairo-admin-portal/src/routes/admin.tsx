import { useEffect } from "react";
import { Outlet, createFileRoute, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  AdminAccessChecking,
  AdminAccessDenied,
  AdminAccessExpired,
} from "@/features/admin/auth/admin-access";
import { AdminAuthProvider, useAdminAuth } from "@/features/admin/auth/admin-auth";
import { normalizeAdminRedirect } from "@/features/admin/auth/redirects";
import { AdminShell } from "@/features/admin/shell/admin-shell";

const PUBLIC_ADMIN_ROUTES = new Set<string>(["/admin/login", "/admin/forgot-password"]);

function isPublicAdminPath(pathname: string): boolean {
  const trimmed = pathname.endsWith("/") && pathname.length > 1 ? pathname.slice(0, -1) : pathname;
  return PUBLIC_ADMIN_ROUTES.has(trimmed);
}

export const Route = createFileRoute("/admin")({
  head: () => ({
    meta: [
      { title: "Kairo Operations" },
      { name: "description", content: "Kairo Operations — internal trust infrastructure." },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: AdminLayout,
});

function AdminLayout() {
  return (
    <AdminAuthProvider>
      <AdminRouter />
    </AdminAuthProvider>
  );
}

function AdminRouter() {
  const auth = useAdminAuth();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isPublic = isPublicAdminPath(pathname);

  useEffect(() => {
    if (auth.status === "checking") return;
    if (auth.status === "authenticated" && isPublic) {
      navigate({ to: "/admin", replace: true });
      return;
    }
    if (auth.status !== "authenticated" && !isPublic) {
      const redirect =
        pathname && pathname !== "/admin/login"
          ? normalizeAdminRedirect(pathname, "/admin")
          : undefined;
      navigate({
        to: "/admin/login",
        replace: true,
        search: { redirect },
      });
    }
  }, [auth.status, isPublic, pathname, navigate]);

  if (auth.status === "checking") return <AdminAccessChecking />;

  // Public admin routes (login / forgot password) render standalone.
  if (isPublic) {
    if (auth.status === "authenticated") return <AdminAccessChecking />;
    return <Outlet />;
  }

  if (auth.status === "expired") return <AdminAccessExpired />;
  if (auth.status !== "authenticated") return <AdminAccessDenied />;

  return (
    <AdminShell>
      <Outlet />
    </AdminShell>
  );
}
