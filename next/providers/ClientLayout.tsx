"use client";

import { ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { NavLink, usePathname } from "@/components/use-nav";
import { LogOut, Menu, Loader2, Send } from "lucide-react";
import { cn } from "@/lib/utils";
import { NAV } from "@/constants/nav";
import { useAuth } from "@/providers/auth";

function Logo() {
  return (
    <div className="flex items-center gap-2">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground shadow-sm">
        <Send size={16} className="-rotate-45" />
      </div>
      <span className="text-base font-bold tracking-tight">
        Deal<span className="text-primary">Wing</span>
      </span>
    </div>
  );
}

function Sidebar() {
  const { user } = useAuth();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <>
      <aside className={cn(
        "fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-border bg-sidebar text-sidebar-foreground transition-transform md:translate-x-0",
        open ? "translate-x-0" : "-translate-x-full",
      )}>
        <div className="flex h-14 items-center border-b border-border px-4">
          <Logo />
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-3">
          {NAV.map((n, i) => (
            <div key={n.to}>
              {n.group && NAV[i - 1]?.group !== n.group && (
                <div className="px-3 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                  {n.group}
                </div>
              )}
              <NavLink to={n.to} end={n.end} onClick={() => setOpen(false)}
                className={({ isActive }: { isActive: boolean }) => cn(
                  "flex items-center gap-3 rounded-lg border-l-2 px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "border-l-primary bg-accent text-primary"
                    : "border-l-transparent text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                )}>
                <n.icon size={18} /> {n.label}
              </NavLink>
            </div>
          ))}
        </nav>
        <div className="border-t border-border p-3 text-xs text-muted-foreground">
          {user?.name && <div className="truncate font-medium text-foreground">{user.name}</div>}
          DealWing · Growth OS
        </div>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-black/40 md:hidden" onClick={() => setOpen(false)} />}
    </>
  );
}

function Header() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-background/80 px-4 backdrop-blur">
      <button className="text-muted-foreground hover:text-foreground md:hidden" onClick={() => setOpen((o) => !o)}>
        <Menu size={20} />
      </button>
      <div className="flex-1 text-sm text-muted-foreground">DealWing</div>
      <div className="flex items-center gap-3">
        <div className="text-right text-sm leading-tight">
          <div className="font-medium text-foreground">{user?.name}</div>
          <div className="text-xs capitalize text-muted-foreground">{user?.role}</div>
        </div>
        <button onClick={logout} title="Log out"
          className="grid h-9 w-9 place-items-center rounded-full bg-secondary text-secondary-foreground transition-colors hover:bg-accent hover:text-primary">
          <LogOut size={16} />
        </button>
      </div>
      {open && <div className="fixed inset-0 z-30 bg-black/40 md:hidden" onClick={() => setOpen(false)} />}
    </header>
  );
}

function AuthGate({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <div className="grid min-h-screen place-items-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex flex-1 flex-col md:pl-60">
        <Header />
        <main className="mx-auto w-full max-w-6xl flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}

export function ClientLayout({ children }: { children: ReactNode }) {
  return <AuthGate>{children}</AuthGate>;
}
