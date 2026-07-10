import { ReactNode, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/** Lightweight positioned popover (no Radix, consistent with dialog.tsx/tabs.tsx).
 * Closes on outside click or Escape. `children` may be a render function that
 * receives `close()`, for content with its own Apply/Cancel actions. */
export function Popover({ trigger, children, align = "start", className }: {
  trigger: (props: { onClick: () => void; open: boolean }) => ReactNode;
  children: ReactNode | ((close: () => void) => ReactNode);
  align?: "start" | "end";
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const close = () => setOpen(false);

  return (
    <div className="relative inline-block" ref={ref}>
      {trigger({ onClick: () => setOpen((o) => !o), open })}
      {open && (
        <div
          className={cn(
            "absolute z-50 mt-2 animate-fade-in",
            align === "end" ? "right-0" : "left-0",
            className
          )}
        >
          {typeof children === "function" ? children(close) : children}
        </div>
      )}
    </div>
  );
}
