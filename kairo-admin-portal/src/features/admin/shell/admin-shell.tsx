import { useState, type ReactNode } from "react";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  Bell,
  ChevronLeft,
  ChevronRight,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Search,
  Settings,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  X,
  Building2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Toaster } from "@/components/ui/sonner";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";
import { AdminEnvironmentNotice } from "../components/admin-environment-notice";
import { useAdminAccess } from "../auth/admin-access";
import { useAdminAuth } from "../auth/admin-auth";
import { KairoLogo } from "@/features/branding/kairo-logo";

interface NavItem {
  label: string;
  to: string;
  icon: typeof LayoutDashboard;
  description: string;
}

// PERMANENT navigation — do not add, remove or rename entries.
const NAV: NavItem[] = [
  {
    label: "Overview",
    to: "/admin",
    icon: LayoutDashboard,
    description: "Growth, operations and urgent activity",
  },
  {
    label: "Verifications",
    to: "/admin/verifications",
    icon: ShieldCheck,
    description: "Verification queue, cases and tasks",
  },
  {
    label: "Users",
    to: "/admin/users",
    icon: Users,
    description: "Candidate accounts and profiles",
  },
  {
    label: "Registry",
    to: "/admin/registry",
    icon: Building2,
    description: "Organizations and canonical records",
  },
  {
    label: "Communications",
    to: "/admin/communications",
    icon: MessageSquare,
    description: "Outreach, email delivery and templates",
  },
  {
    label: "Risk",
    to: "/admin/risk",
    icon: ShieldAlert,
    description: "Trust & Safety investigations, duplicates, document anomalies",
  },
  {
    label: "System",
    to: "/admin/system",
    icon: SlidersHorizontal,
    description: "Platform health, roles and configuration",
  },
];

export function AdminShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = useRouterState({ select: (r) => r.location.pathname });
  const current = matchNav(pathname);
  const { admin } = useAdminAccess();
  const { logout } = useAdminAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout("user");
    toast.success("Signed out", { description: "Your admin session has ended." });
    navigate({ to: "/admin/login", replace: true, search: { redirect: undefined } });
  };

  return (
    <div className="flex min-h-screen w-full bg-muted/30 text-foreground">
      {/* Desktop sidebar */}
      <aside
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 border-r border-border bg-background transition-[width] duration-200 lg:flex lg:flex-col",
          collapsed ? "w-16" : "w-60",
        )}
        aria-label="Admin navigation"
      >
        <SidebarInner
          collapsed={collapsed}
          pathname={pathname}
          onCollapseToggle={() => setCollapsed((c) => !c)}
          admin={admin}
          onLogout={handleLogout}
        />
      </aside>

      {/* Mobile drawer */}
      {mobileOpen ? (
        <div
          className="fixed inset-0 z-50 lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Admin navigation"
        >
          <button
            aria-label="Close navigation"
            className="absolute inset-0 bg-foreground/40"
            onClick={() => setMobileOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col border-r border-border bg-background">
            <div className="flex items-center justify-between border-b border-border px-3 py-2">
              <BrandMark />

              <button
                onClick={() => setMobileOpen(false)}
                className="rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                aria-label="Close navigation"
              >
                <X aria-hidden className="size-4" />
              </button>
            </div>
            <SidebarInner
              collapsed={false}
              pathname={pathname}
              admin={admin}
              onNavigate={() => setMobileOpen(false)}
              onLogout={handleLogout}
            />
          </div>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <AdminEnvironmentNotice variant="banner" />
        {/* Top header */}
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-background/95 px-3 backdrop-blur sm:px-6">
          <button
            className="rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground lg:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <Menu aria-hidden className="size-5" />
          </button>

          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold text-foreground">{current.label}</h1>
            <p className="hidden truncate text-xs text-muted-foreground sm:block">
              {current.description}
            </p>
          </div>

          <div className="relative hidden md:block">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
            />
            <input
              type="search"
              placeholder="Search users, requests, organizations…"
              aria-label="Global search"
              className="h-8 w-72 rounded-md border border-border bg-card pl-7 pr-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          <button
            className="relative rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Notifications"
          >
            <Bell aria-hidden className="size-4" />
            <span
              className="absolute right-1 top-1 size-1.5 rounded-full bg-rose-500"
              aria-hidden
            />
          </button>

          <DropdownMenu>
            <DropdownMenuTrigger
              aria-label="Admin profile menu"
              className="flex items-center gap-2 rounded-md border border-transparent px-1.5 py-1 text-xs hover:border-border hover:bg-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="flex size-6 items-center justify-center rounded-full bg-foreground text-[10px] font-semibold text-background">
                {admin?.initials ?? "—"}
              </span>
              <span className="hidden text-left sm:block">
                <span className="block font-medium text-foreground">
                  {admin?.name ?? "Signed out"}
                </span>
                <span className="block text-[10px] text-muted-foreground">{admin?.role ?? ""}</span>
              </span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              {admin ? (
                <>
                  <DropdownMenuLabel className="flex flex-col gap-0.5">
                    <span className="text-xs font-semibold">{admin.name}</span>
                    <span className="truncate text-[10px] font-normal text-muted-foreground">
                      {admin.email}
                    </span>
                    <span className="mt-1 inline-flex w-fit items-center rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                      {admin.role}
                    </span>
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                </>
              ) : null}
              <DropdownMenuItem
                onSelect={handleLogout}
                className="text-destructive focus:text-destructive"
              >
                <LogOut aria-hidden className="mr-2 size-4" />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>

        <main className="min-w-0 flex-1 px-3 py-4 sm:px-6 sm:py-6">{children}</main>
      </div>
      <Toaster />
    </div>
  );
}

function SidebarInner({
  collapsed,
  pathname,
  onCollapseToggle,
  onNavigate,
  admin,
  onLogout,
}: {
  collapsed: boolean;
  pathname: string;
  onCollapseToggle?: () => void;
  onNavigate?: () => void;
  admin?: { name: string; role: string; initials: string; email: string };
  onLogout?: () => void;
}) {
  return (
    <>
      <div
        className={cn(
          "hidden items-center gap-2 border-b border-border px-3 py-3 lg:flex",
          collapsed && "justify-center px-0",
        )}
      >
        {collapsed ? <BrandMarkCompact /> : <BrandMark />}
      </div>

      <nav className="flex-1 overflow-y-auto p-2" aria-label="Sections">
        <ul className="space-y-0.5">
          {NAV.map((item) => {
            const active = isActive(pathname, item.to);
            const Icon = item.icon;
            return (
              <li key={item.to}>
                <Link
                  to={item.to}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  title={collapsed ? item.label : undefined}
                  className={cn(
                    "group flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm font-medium transition-colors",
                    active
                      ? "bg-foreground text-background"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground",
                    collapsed && "justify-center px-0",
                  )}
                >
                  <Icon aria-hidden className="size-4 shrink-0" />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="border-t border-border p-2">
        {!collapsed && admin ? (
          <div className="mb-2 rounded-md bg-muted/60 p-2">
            <div className="flex items-center gap-2">
              <span className="flex size-7 items-center justify-center rounded-full bg-foreground text-[11px] font-semibold text-background">
                {admin.initials}
              </span>
              <div className="min-w-0">
                <p className="truncate text-xs font-semibold text-foreground">{admin.name}</p>
                <p className="truncate text-[10px] text-muted-foreground">
                  {admin.role} · {admin.email}
                </p>
              </div>
            </div>
          </div>
        ) : null}
        <ul className="space-y-0.5">
          <li>
            <button
              className={cn(
                "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground",
                collapsed && "justify-center px-0",
              )}
              title="Settings"
            >
              <Settings aria-hidden className="size-4" />
              {!collapsed && <span>Settings</span>}
            </button>
          </li>
          <li>
            <button
              type="button"
              onClick={onLogout}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground",
                collapsed && "justify-center px-0",
              )}
              title="Sign out"
            >
              <LogOut aria-hidden className="size-4" />
              {!collapsed && <span>Sign out</span>}
            </button>
          </li>
        </ul>
        {onCollapseToggle ? (
          <button
            onClick={onCollapseToggle}
            className="mt-2 hidden w-full items-center justify-center rounded-md border border-border py-1 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground lg:flex"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? (
              <ChevronRight aria-hidden className="size-3.5" />
            ) : (
              <ChevronLeft aria-hidden className="size-3.5" />
            )}
          </button>
        ) : null}
      </div>
    </>
  );
}

function BrandMark() {
  return (
    <Link to="/admin" aria-label="Kairo Operations — Overview" className="flex items-center gap-2">
      <KairoLogo width={128} />
    </Link>
  );
}

function BrandMarkCompact() {
  return (
    <Link
      to="/admin"
      aria-label="Kairo Operations — Overview"
      className="flex size-9 items-center justify-center"
    >
      <KairoLogo width={32} showWordmark={false} />
    </Link>
  );
}

function matchNav(pathname: string): NavItem {
  // Prefer the most-specific match, falling back to Overview.
  const sorted = [...NAV].sort((a, b) => b.to.length - a.to.length);
  return sorted.find((n) => isActive(pathname, n.to)) ?? NAV[0];
}

function isActive(pathname: string, to: string): boolean {
  if (to === "/admin") return pathname === "/admin" || pathname === "/admin/";
  return pathname === to || pathname.startsWith(`${to}/`);
}
