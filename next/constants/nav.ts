import type { IconSvgElement } from "@hugeicons/react";
import {
  Analytics01Icon,
  CheckListIcon,
  Clock01Icon,
  Home01Icon,
  Sent02Icon,
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
  { to: "/competitors", label: "Competitors", icon: UserGroupIcon, group: "Understand" },
  { to: "/plan", label: "Plan", icon: CheckListIcon, group: "Act" },
  { to: "/posts", label: "Posts", icon: Sent02Icon, group: "Act" },
  { to: "/schedulers", label: "System health", icon: Clock01Icon, group: "System" },
];
