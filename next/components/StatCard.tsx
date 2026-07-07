"use client";

import { ReactNode } from "react";
import { TrendingDown, TrendingUp } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function StatCard({ label, value, sub, icon, trend, className }: {
  label: string; value: string; sub?: ReactNode; icon?: ReactNode; trend?: { value: number; label?: string; positiveIsGood?: boolean }; className?: string;
}) {
  const isGood = trend ? (trend.positiveIsGood ?? true) ? trend.value >= 0 : trend.value <= 0 : true;
  return (
    <Card className={cn("", className)}>
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div className="min-w-0">
            <p className="truncate text-xs text-muted-foreground">{label}</p>
            <p className="mt-0.5 text-2xl font-bold tracking-tight">{value}</p>
            {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
            {trend && (
              <div className={cn("mt-1 flex items-center gap-1 text-xs font-medium", isGood ? "text-green-600" : "text-red-600")}>
                {isGood ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                <span>{trend.value >= 0 ? "+" : ""}{trend.value}%</span>
                {trend.label && <span className="text-muted-foreground font-normal">{trend.label}</span>}
              </div>
            )}
          </div>
          {icon && <div className="shrink-0 text-muted-foreground">{icon}</div>}
        </div>
      </CardContent>
    </Card>
  );
}
