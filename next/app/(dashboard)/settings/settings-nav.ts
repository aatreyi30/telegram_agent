import type { IconSvgElement } from "@hugeicons/react";
import {
  Building01Icon, Satellite01Icon, UserGroupIcon, UserIcon,
} from "@hugeicons/core-free-icons";

export interface SettingsNavItem {
  key: string;
  label: string;
  icon: IconSvgElement;
  description: string;
  ownerOnly: boolean;
}

// Shared by settings/layout.tsx (left-hand nav) and the owner-only route guard —
// single source of truth for what pages exist and who can see them, instead of
// repeating the isOwner check per page.
export const SETTINGS_NAV: SettingsNavItem[] = [
  { key: "profile", label: "Profile", icon: UserIcon, description: "Your account and password.", ownerOnly: false },
  { key: "channels", label: "Channels", icon: Satellite01Icon, description: "The Telegram channels you own and track.", ownerOnly: true },
  { key: "org", label: "Organization", icon: Building01Icon, description: "Company details and affiliate link settings.", ownerOnly: true },
  { key: "users", label: "Users", icon: UserGroupIcon, description: "Teammates and their access level.", ownerOnly: true },
  { key: "competitors", label: "Competitors", icon: UserGroupIcon, description: "Manually track direct and indirect competitors.", ownerOnly: true },
];
