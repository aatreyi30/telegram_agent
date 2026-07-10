import { ReactNode } from "react";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { Card } from "./ui/card";
import { cn } from "@/lib/utils";

export function StatCard({ label, value, sub, icon, trend }: {
  label: string;
  value: ReactNode;
  sub?: string;
  icon?: ReactNode;
  /** Optional "vs previous period" delta. `positiveIsGood` (default true) controls
   * whether an increase renders green (e.g. views) or red (e.g. bounce rate). */
  trend?: { value: number; label?: string; positiveIsGood?: boolean };
}) {
  const dir = trend ? (trend.value > 0 ? "up" : trend.value < 0 ? "down" : "flat") : null;
  const good = trend?.positiveIsGood ?? true;
  const isGood = dir === null || dir === "flat" ? null : (dir === "up") === good;

  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-2xl font-bold tracking-tight">{value}</div>
          <div className="mt-1 text-sm text-muted-foreground">{label}</div>
        </div>
        {icon && <div className="text-primary/70">{icon}</div>}
      </div>
      {(sub || trend) && (
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          {trend && (
            <span
              className={cn(
                "inline-flex items-center gap-0.5 font-medium",
                isGood === null ? "text-muted-foreground" : isGood ? "text-success" : "text-destructive"
              )}
            >
              {dir === "up" ? <ArrowUp className="h-3 w-3" /> : dir === "down" ? <ArrowDown className="h-3 w-3" /> : <Minus className="h-3 w-3" />}
              {Math.abs(trend.value).toFixed(Number.isInteger(trend.value) ? 0 : 1)}%
            </span>
          )}
          {trend?.label && <span>{trend.label}</span>}
          {sub && <span>{sub}</span>}
        </div>
      )}
    </Card>
  );
}
