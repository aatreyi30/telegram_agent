import { cn } from "@/lib/utils";

/** A small pulsing dot + label — the "the agent is actually running" signal.
 * Purely presentational; callers decide when it's true (e.g. schedulers on
 * and a job ran recently) vs a plain static dot for "off"/"stale". */
export function LivePulse({ label = "Live", active = true, className }: { label?: string; active?: boolean; className?: string }) {
  return (
    <span className={cn(
      "inline-flex items-center gap-1.5 text-xs font-medium",
      active ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground",
      className,
    )}>
      <span className="relative flex h-2 w-2">
        {active && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />}
        <span className={cn("relative inline-flex h-2 w-2 rounded-full", active ? "bg-emerald-500" : "bg-muted-foreground/50")} />
      </span>
      {label}
    </span>
  );
}
