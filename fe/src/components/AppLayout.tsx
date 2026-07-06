import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3, Bot, CalendarDays, Clock, GitCompare, LayoutDashboard, Lightbulb,
  ListOrdered, LogOut, Menu, Package, Send, Settings as SettingsIcon, Store, TrendingUp, Users2,
} from "lucide-react";
import { api } from "@/services/api";
import { useAuth } from "@/providers/auth";
import { cn } from "@/lib/utils";
import { Logo } from "./Logo";

// Grouped so the sidebar reads clearly: what runs it, what it learned, what it produced.
const NAV = [
  { to: "/app", label: "Overview", icon: LayoutDashboard, end: true, group: "" },
  { to: "/app/agent", label: "Agent", icon: Bot, group: "Run" },
  { to: "/app/schedulers", label: "Schedulers", icon: Clock, group: "Run" },
  { to: "/app/insights", label: "Insights", icon: Lightbulb, group: "Understand" },
  { to: "/app/analytics", label: "Analytics", icon: BarChart3, group: "Understand" },
  { to: "/app/day", label: "Day view", icon: CalendarDays, group: "Understand" },
  { to: "/app/competitors", label: "Competitors", icon: Users2, group: "Understand" },
  { to: "/app/comparison", label: "You vs competitors", icon: GitCompare, group: "Understand" },
  { to: "/app/growth", label: "Growth", icon: TrendingUp, group: "Understand" },
  { to: "/app/merchants", label: "Merchants", icon: Store, group: "Understand" },
  { to: "/app/plan", label: "Plan", icon: ListOrdered, group: "Act" },
  { to: "/app/drafts", label: "Drafts", icon: Send, group: "Act" },
  { to: "/app/queue", label: "Schedule", icon: Package, group: "Act" },
  { to: "/app/settings", label: "Settings", icon: SettingsIcon, group: "" },
];

export function AppLayout() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const { data: ov } = useQuery({ queryKey: ["overview"], queryFn: () => api.get<any>("/api/overview") });
  const channel = ov?.channel?.username ? `@${ov.channel.username}` : "";

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r bg-sidebar text-sidebar-foreground transition-transform md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="flex h-14 items-center border-b border-white/10 px-4">
          <Logo />
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-3">
          {NAV.map((n, i) => (
            <div key={n.to}>
              {n.group && NAV[i - 1]?.group !== n.group && (
                <div className="px-3 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-sidebar-foreground/40">
                  {n.group}
                </div>
              )}
              <NavLink
                to={n.to}
                end={n.end}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    isActive ? "bg-primary text-primary-foreground" : "text-sidebar-foreground/75 hover:bg-white/10 hover:text-white"
                  )
                }
              >
                <n.icon size={18} /> {n.label}
              </NavLink>
            </div>
          ))}
        </nav>
        <div className="border-t border-white/10 p-3 text-xs text-sidebar-foreground/60">
          DealWing · Growth OS
        </div>
      </aside>

      {/* Main */}
      <div className="flex flex-1 flex-col md:pl-60">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur">
          <button className="md:hidden" onClick={() => setOpen((o) => !o)}>
            <Menu size={20} />
          </button>
          <div className="flex-1 text-sm text-muted-foreground">
            {ov?.channel?.title || "—"} {channel && <span className="text-foreground">· {channel}</span>}
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right text-sm leading-tight">
              <div className="font-medium">{user?.name}</div>
              <div className="text-xs text-muted-foreground capitalize">{user?.role}</div>
            </div>
            <button
              onClick={logout}
              title="Log out"
              className="grid h-9 w-9 place-items-center rounded-full bg-secondary hover:bg-secondary/70"
            >
              <LogOut size={16} />
            </button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
      {open && <div className="fixed inset-0 z-30 bg-black/40 md:hidden" onClick={() => setOpen(false)} />}
    </div>
  );
}

export function PageHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-5">
      <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
      {sub && <p className="mt-1 text-sm text-muted-foreground">{sub}</p>}
    </div>
  );
}
