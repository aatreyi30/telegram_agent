import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

/** Fade-and-rise entrance wrapper. Give siblings an increasing `index` (or an
 * explicit `delay` in ms) and they cascade in. Pure CSS (see `.reveal` in
 * globals.css) — no motion library, and fully disabled under reduced-motion. */
export function Reveal({
  children, index = 0, delay, step = 70, className, as: Tag = "div",
}: {
  children: ReactNode;
  index?: number;
  delay?: number;
  step?: number;
  className?: string;
  as?: "div" | "section" | "li";
}) {
  const d = delay ?? index * step;
  return (
    <Tag className={cn("reveal", className)} style={{ "--d": `${d}ms` } as React.CSSProperties}>
      {children}
    </Tag>
  );
}

/** Shimmering placeholder block for loading states. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("shimmer rounded-md", className)} />;
}