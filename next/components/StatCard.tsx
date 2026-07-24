"use client";

import { ReactNode } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { AnalyticsDownIcon, AnalyticsUpIcon } from "@hugeicons/core-free-icons";
import { Card, CardContent } from "@/components/ui/card";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { cn } from "@/lib/utils";

export function StatCard({ label, value, sub, icon, trend, className, variant = "default" }: {
  label: string; value: string; sub?: ReactNode; icon?: ReactNode;
  trend?: { value: number; label?: string; positiveIsGood?: boolean }; className?: string;
  /** "hero" = bigger number + a soft gradient wash, for the one metric per section
   * that should draw the eye first. Use sparingly — everything "hero" is nothing hero. */
  variant?: "default" | "hero";
}) {
  const isGood = trend ? (trend.positiveIsGood ?? true) ? trend.value >= 0 : trend.value <= 0 : true;
  const hero = variant === "hero";
  return (
    <Card className={cn(
      "animate-in fade-in slide-in-from-bottom-1 duration-500",
      hero && "border-primary/20 bg-gradient-to-br from-primary/[0.07] via-card to-card",
      className,
    )}>
      <CardContent className={cn("p-3", hero && "p-4")}>
        <div className="flex items-start justify-between">
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
          {icon && <div className={cn("shrink-0 text-muted-foreground", hero && "text-primary")}>{icon}</div>}
        </div>
      </CardContent>
    </Card>
  );
}
