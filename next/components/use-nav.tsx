"use client";

import { usePathname as useNextPathname } from "next/navigation";
import NextLink from "next/link";
import { ReactNode } from "react";

export function usePathname() {
  return useNextPathname();
}

/** react-router-NavLink-shaped wrapper over next/link's Link — maps `to`→`href`
 * and computes `isActive` from the current pathname, since Next's Link has
 * neither. Supports the same `className={(props: {isActive}) => string}`
 * render-prop pattern react-router's NavLink does, for drop-in compatibility
 * with code ported from the Vite app. */
export function NavLink({ to, end, onClick, className, children }: {
  to: string;
  end?: boolean;
  onClick?: () => void;
  className?: string | ((props: { isActive: boolean }) => string);
  children: ReactNode;
}) {
  const pathname = usePathname();
  const isActive = end ? pathname === to : pathname === to || pathname.startsWith(`${to}/`);
  const resolvedClassName = typeof className === "function" ? className({ isActive }) : className;

  return (
    <NextLink href={to} onClick={onClick} className={resolvedClassName}>
      {children}
    </NextLink>
  );
}
