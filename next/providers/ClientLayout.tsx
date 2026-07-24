"use client";

import { ReactNode, useEffect } from "react";
import { useRouter } from "next/navigation";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  Loading03Icon,
  Logout04Icon,
  MoreHorizontalIcon,
  Sent02Icon,
  Settings02Icon,
} from "@hugeicons/core-free-icons";
import { NavLink, usePathname } from "@/components/use-nav";
import { ActivityToasts } from "@/components/ActivityToasts";
import { cn } from "@/lib/utils";
import { NAV } from "@/constants/nav";
import { useAuth } from "@/providers/auth";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
  sidebarMenuButtonVariants,
} from "@/components/ui/sidebar";

function Logo() {
  return (
    <div className="flex items-center gap-2 px-2 py-1 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground shadow-sm">
        <HugeiconsIcon icon={Sent02Icon} size={16} />
      </div>
      <span className="text-base font-bold tracking-tight group-data-[collapsible=icon]:hidden">
        Deal<span className="text-primary">Wing</span>
      </span>
    </div>
  );
}

function initials(name?: string | null) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  return parts.slice(0, 2).map((p) => p[0]?.toUpperCase() ?? "").join("");
}

const NAV_GROUPS = Array.from(new Set(NAV.map((n) => n.group)));

function AppSidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const router = useRouter();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="border-b border-sidebar-border">
        <Logo />
      </SidebarHeader>
      <SidebarContent>
        {NAV_GROUPS.map((group) => (
          <SidebarGroup key={group || "_root"}>
            {group && <SidebarGroupLabel>{group}</SidebarGroupLabel>}
            <SidebarMenu>
              {NAV.filter((n) => n.group === group).map((n) => {
                const isActive = n.end ? pathname === n.to : pathname === n.to || pathname.startsWith(`${n.to}/`);
                return (
                  <SidebarMenuItem key={n.to}>
                    <NavLink
                      to={n.to}
                      end={n.end}
                      title={n.label}
                      className={cn(
                        sidebarMenuButtonVariants({ variant: "default", size: "default" }),
                        isActive && "bg-sidebar-accent font-medium text-sidebar-accent-foreground",
                      )}
                    >
                      <HugeiconsIcon icon={n.icon} size={18} />
                      <span>{n.label}</span>
                    </NavLink>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter className="border-t border-sidebar-border">
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton size="lg" className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground">
                  <Avatar size="sm" className="rounded-lg">
                    <AvatarFallback className="rounded-lg">{initials(user?.name)}</AvatarFallback>
                  </Avatar>
                  <div className="grid flex-1 text-left text-sm leading-tight">
                    <span className="truncate font-medium">{user?.name}</span>
                    {user?.email && <span className="truncate text-xs text-sidebar-foreground/60">{user.email}</span>}
                  </div>
                  <HugeiconsIcon icon={MoreHorizontalIcon} size={16} className="ml-auto shrink-0 text-sidebar-foreground/60" />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent side="top" align="start" className="w-56">
                <DropdownMenuItem onClick={() => router.push("/settings")}>
                  <HugeiconsIcon icon={Settings02Icon} size={16} /> Settings
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" onClick={logout}>
                  <HugeiconsIcon icon={Logout04Icon} size={16} /> Log out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
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
        <HugeiconsIcon icon={Loading03Icon} size={24} className="animate-spin text-primary" />
      </div>
    );
  }

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border bg-background/80 px-4 backdrop-blur">
          <SidebarTrigger />
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 p-4 md:p-6">{children}</main>
      </SidebarInset>
      <ActivityToasts />
    </SidebarProvider>
  );
}

export function ClientLayout({ children }: { children: ReactNode }) {
  return <AuthGate>{children}</AuthGate>;
}
