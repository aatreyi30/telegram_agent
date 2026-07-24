"use client";

import { useEffect, useRef, useState } from "react";

/** Counts up from 0 to the number embedded in a formatted string ("28,467",
 * "+1,963", "0.3%", "₹988") on mount/value-change, preserving whatever prefix,
 * suffix, and comma/decimal formatting the caller already applied. Falls back
 * to rendering the string as-is when no number is found, or instantly when the
 * viewer has requested reduced motion. */
export function AnimatedNumber({ value, durationMs = 700 }: { value: string; durationMs?: number }) {
  const match = value.match(/-?[\d,]+\.?\d*/);
  const numeric = match ? match[0] : null;
  const target = numeric ? parseFloat(numeric.replace(/,/g, "")) : null;
  const decimals = numeric?.includes(".") ? numeric.split(".")[1].length : 0;
  const [display, setDisplay] = useState(target ?? 0);

  useEffect(() => {
    if (target == null) return;
    const reduced = typeof window !== "undefined"
      && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced) { setDisplay(target); return; }
    let raf: number;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(target * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
      else setDisplay(target);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);

  if (target == null || !numeric) return <>{value}</>;
  const formatted = decimals
    ? display.toFixed(decimals)
    : Math.round(display).toLocaleString();
  return <>{value.replace(numeric, formatted)}</>;
}
