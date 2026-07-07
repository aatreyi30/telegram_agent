import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { LogOut, Menu } from "lucide-react";
import { useAuth } from "@/providers/auth";
import { cn } from "@/lib/utils";
import { NAV } from "@/constants/nav";
import { useOverview } from "@/queries/queries";
import { Logo } from "./Logo";

export function AppLayout() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const { data: ov } = useOverview();
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
