import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import { AdminPortalLoading } from "@/features/admin/auth/admin-access";
import { createAdminAuthAdapter } from "@/features/admin/auth/create-admin-auth-adapter";
import { resolveAdminLandingPath } from "@/features/admin/auth/landing";

export const Route = createFileRoute("/")({
  component: Index,
});

function Index() {
  const navigate = useNavigate();

  useEffect(() => {
    const adapter = createAdminAuthAdapter();

    void resolveAdminLandingPath(adapter).then((target) => {
      navigate({
        to: target,
        replace: true,
      });
    });
  }, [navigate]);

  return <AdminPortalLoading />;
}
