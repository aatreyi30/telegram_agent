import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}

export function fmtPct(n: number | null | undefined, signed = false): string {
  if (n === null || n === undefined) return "—";
  const s = signed && n > 0 ? "+" : "";
  return `${s}${Math.round(n)}%`;
}
