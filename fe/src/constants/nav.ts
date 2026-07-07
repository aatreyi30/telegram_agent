import type { LucideIcon } from "lucide-react";
import {
  BarChart3, CalendarDays, LayoutDashboard, Lightbulb,
  ListOrdered, Package, Send, Settings as SettingsIcon, TrendingUp, Users2,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  group: string;
}

// Grouped so the sidebar reads clearly: what it learned, what it produced.
// NOTE: Competitors now absorbs Merchants (plan.md Phase 3) — no separate entry.
export const NAV: NavItem[] = [
  { to: "/app", label: "Overview", icon: LayoutDashboard, end: true, group: "" },
  { to: "/app/insights", label: "Insights", icon: Lightbulb, group: "Understand" },
  { to: "/app/analytics", label: "Analytics", icon: BarChart3, group: "Understand" },
  { to: "/app/day", label: "Day view", icon: CalendarDays, group: "Understand" },
  { to: "/app/competitors", label: "Competitors", icon: Users2, group: "Understand" },
  { to: "/app/growth", label: "Growth", icon: TrendingUp, group: "Understand" },
  { to: "/app/plan", label: "Plan", icon: ListOrdered, group: "Act" },
  { to: "/app/drafts", label: "Drafts", icon: Send, group: "Act" },
  { to: "/app/queue", label: "Schedule", icon: Package, group: "Act" },
  { to: "/app/settings", label: "Settings", icon: SettingsIcon, group: "" },
];
