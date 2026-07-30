"use client";

import { ReactNode } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { AnalyticsDownIcon, AnalyticsUpIcon, ChartLineData02Icon } from "@hugeicons/core-free-icons";
import { Card, CardContent } from "@/components/ui/card";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { cn } from "@/lib/utils";

export function StatCard({ label, value, sub, icon, trend, className, variant = "default", onClick }: {
  label: string; value: string; sub?: ReactNode; icon?: ReactNode;
  trend?: { value: number; label?: string; positiveIsGood?: boolean }; className?: string;
  /** "hero" = bigger number + a soft gradient wash, for the one metric per section
   * that should draw the eye first. Use sparingly — everything "hero" is nothing hero. */
  variant?: "default" | "hero";
  /** When set, the whole card becomes a button and shows a small chart-icon affordance —
   * e.g. "tap this stat to see its trend chart" instead of a chart sitting on the page
   * by default. */
  onClick?: () => void;
}) {
  const isGood = trend ? (trend.positiveIsGood ?? true) ? trend.value >= 0 : trend.value <= 0 : true;
  const hero = variant === "hero";
  const content = (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-xs text-muted-foreground">{label}</p>
          <p className={cn(
            "mt-0.5 font-semibold tracking-tight tabular-nums",
            hero ? "text-3xl bg-gradient-to-br from-foreground to-foreground/70 bg-clip-text" : "text-xl",
          )}>
            <AnimatedNumber value={value} />
          </p>
          {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
          {trend && (
            <div className={cn("mt-1 flex items-center gap-1 text-xs font-medium", isGood ? "text-green-600" : "text-red-600")}>
              {isGood ? <HugeiconsIcon icon={AnalyticsUpIcon} className="h-3 w-3" /> : <HugeiconsIcon icon={AnalyticsDownIcon} className="h-3 w-3" />}
              <span>{trend.value >= 0 ? "+" : ""}{trend.value}%</span>
              {trend.label && <span className="text-muted-foreground font-normal">{trend.label}</span>}
            </div>
          )}
        </div>
        {icon && (
          <div className={cn(
            "grid h-9 w-9 shrink-0 place-items-center rounded-full",
            hero ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground",
          )}>
            {icon}
          </div>
        )}
      </div>
      {onClick && (
        // mt-auto keeps this pinned to the card's bottom edge regardless of how tall the
        // label/value/sub block above it is — otherwise cards with a `sub` line push their
        // divider lower than cards without one, and a row of them looks misaligned.
        <div className="mt-2 flex items-center gap-1 border-t border-primary/15 pt-2 text-[11px] font-medium text-primary">
          <HugeiconsIcon icon={ChartLineData02Icon} className="h-3 w-3" />
          View chart
        </div>
      )}
    </div>
  );
  return (
    <Card className={cn(
      "animate-in fade-in slide-in-from-bottom-1 duration-500",
      hero && "border-primary/20 bg-gradient-to-br from-primary/[0.07] via-card to-card",
      onClick && "h-full border-primary/25 bg-primary/[0.02] transition-all hover:border-primary/50 hover:bg-primary/[0.06] hover:shadow-sm",
      className,
    )}>
      {onClick ? (
        <button type="button" onClick={onClick} className="flex h-full w-full flex-col text-left">
          <CardContent className={cn("flex h-full flex-col p-3", hero && "p-4")}>{content}</CardContent>
        </button>
      ) : (
        <CardContent className={cn("p-3", hero && "p-4")}>{content}</CardContent>
      )}
    </Card>
  );
}
