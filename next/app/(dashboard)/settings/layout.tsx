"use client";

import type { ReactNode } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { NavLink, usePathname } from "@/components/use-nav";
import { cn } from "@/lib/utils";
import { useAuth } from "@/providers/auth";
import { SETTINGS_NAV } from "./settings-nav";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const pathname = usePathname();
  const items = SETTINGS_NAV.filter((i) => !i.ownerOnly || isOwner);
  const active = items.find((i) => pathname === `/settings/${i.key}` || pathname.startsWith(`/settings/${i.key}/`))
    ?? items[0];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">Your profile, channels, the organization, users, and competitors.</p>
      </div>
      <div className="flex flex-col gap-8 md:flex-row">
        <nav className="flex shrink-0 gap-1 overflow-x-auto pb-1 md:w-52 md:flex-col md:overflow-visible md:pb-0">
          {items.map((item) => (
            <NavLink
              key={item.key}
              to={`/settings/${item.key}`}
              className={({ isActive }) => cn(
                "flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors",
                isActive
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
              )}
            >
              <HugeiconsIcon icon={item.icon} size={17} className="shrink-0" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="min-w-0 flex-1 space-y-4">
          {active && (
            <div>
              <h2 className="text-lg font-semibold">{active.label}</h2>
              <p className="text-sm text-muted-foreground">{active.description}</p>
            </div>
          )}
          {children}
        </div>
      </div>
    </div>
  );
}
