import type { LucideIcon } from "lucide-react";
import {
  BarChart3, CalendarDays, CreditCard, LayoutDashboard, Lightbulb,
  ListOrdered, Package, Send, Settings as SettingsIcon, TrendingUp, Users2,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  group: string;
}

export const NAV: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true, group: "" },
  { to: "/insights", label: "Insights", icon: Lightbulb, group: "Understand" },
  { to: "/analytics", label: "Analytics", icon: BarChart3, group: "Understand" },
  { to: "/day", label: "Day view", icon: CalendarDays, group: "Understand" },
  { to: "/competitors", label: "Competitors", icon: Users2, group: "Understand" },
  { to: "/growth", label: "Growth", icon: TrendingUp, group: "Understand" },
  { to: "/plan", label: "Plan", icon: ListOrdered, group: "Act" },
  { to: "/billing", label: "Billing", icon: CreditCard, group: "" },
  { to: "/drafts", label: "Drafts", icon: Send, group: "Act" },
  { to: "/queue", label: "Schedule", icon: Package, group: "Act" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, group: "" },
];
