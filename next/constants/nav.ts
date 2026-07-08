import type { IconSvgElement } from "@hugeicons/react";
import {
  Analytics01Icon,
  Calendar03Icon,
  ChartUpIcon,
  CheckListIcon,
  Home01Icon,
  Sent02Icon,
  Package02Icon,
  UserGroupIcon,
} from "@hugeicons/core-free-icons";

export interface NavItem {
  to: string;
  label: string;
  icon: IconSvgElement;
  end?: boolean;
  group: string;
}

export const NAV: NavItem[] = [
  { to: "/", label: "Overview", icon: Home01Icon, end: true, group: "" },
  { to: "/analytics", label: "Analytics", icon: Analytics01Icon, group: "Understand" },
  { to: "/day", label: "Day view", icon: Calendar03Icon, group: "Understand" },
  { to: "/competitors", label: "Competitors", icon: UserGroupIcon, group: "Understand" },
  { to: "/growth", label: "Growth", icon: ChartUpIcon, group: "Understand" },
  { to: "/plan", label: "Plan", icon: CheckListIcon, group: "Act" },
  { to: "/drafts", label: "Drafts", icon: Sent02Icon, group: "Act" },
  { to: "/queue", label: "Schedule", icon: Package02Icon, group: "Act" },
];
