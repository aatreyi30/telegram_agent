import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

/** Small pill marking a block as AI-authored (grounded in report data + fact-checked),
 * so the UI stays honest about what's AI reasoning vs. deterministic computation. */
export function AiBadge({ label = "AI", className }: { label?: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-violet-400/40 bg-gradient-to-r from-violet-500/15 to-fuchsia-500/10 px-2 py-0.5 text-[11px] font-medium text-violet-600 shadow-[0_0_0_1px_rgba(139,92,246,0.05)] transition-transform hover:scale-105 dark:text-violet-300",
        className,
      )}
      title="Written by AI — grounded in your report data and fact-checked"
    >
      <Sparkles className="h-3 w-3 animate-pulse" />
      {label}
    </span>
  );
}
