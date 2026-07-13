"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/providers/auth";

/**
 * Route guard for the owner-only settings pages (channels/org/users/competitors) —
 * the single place that enforces "non-owners can't be here", so it isn't
 * copy-pasted into every page. Mirrors the old in-page tab switcher's `isOwner`
 * check, but as a redirect: a non-owner hitting one of these URLs directly gets
 * sent back to /settings/profile (which everyone can see).
 */
export function OwnerOnly({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const router = useRouter();
  const isOwner = user?.role === "owner";

  useEffect(() => {
    if (user && !isOwner) router.replace("/settings/profile");
  }, [user, isOwner, router]);

  if (!isOwner) return null;
  return <>{children}</>;
}
