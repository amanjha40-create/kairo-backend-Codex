import { Outlet, createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/admin/risk")({
  head: () => ({
    meta: [
      { title: "Risk & Trust & Safety — Kairo Admin" },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: () => <Outlet />,
});
