import { ReactNode, useId, useState } from "react";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

/** Lightweight hover/focus tooltip (no Radix, consistent with the rest of ui/). */
export function Tooltip({ content, children, className }: {
  content: ReactNode; children: ReactNode; className?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <span
        aria-describedby={id}
        tabIndex={0}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="inline-flex cursor-help"
      >
        {children}
      </span>
      {open && (
        <span
          role="tooltip"
          id={id}
          className={cn(
            "pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 w-max max-w-64 -translate-x-1/2 " +
              "rounded-md border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-md animate-fade-in",
            className
          )}
        >
          {content}
        </span>
      )}
    </span>
  );
}

/** Small "(?)" info-icon affordance for explaining a jargon term inline, e.g. next
 * to a "views/day" column header — hover/focus reveals a one-line explanation. */
export function InfoTip({ text, className }: { text: string; className?: string }) {
  return (
    <Tooltip content={text}>
      <Info className={cn("h-3.5 w-3.5 text-muted-foreground", className)} />
    </Tooltip>
  );
}
