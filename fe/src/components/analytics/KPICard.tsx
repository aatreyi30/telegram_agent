import { useCallback, useEffect, useRef, useState } from "react";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn, fmtNum, fmtPct } from "@/lib/utils";
import { SparklineChart } from "./charts";

function AnimatedCounter({ value, duration = 800 }: { value: number; duration?: number }) {
  const [display, setDisplay] = useState(0);
  const prevRef = useRef(0);
  const rafRef = useRef<number>();
  useEffect(() => {
    const start = prevRef.current;
    const diff = value - start;
    if (Math.abs(diff) < 1) { setDisplay(value); prevRef.current = value; return; }
    const startTime = performance.now();
    const animate = (now: number) => {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(Math.round(start + diff * eased));
      if (progress < 1) rafRef.current = requestAnimationFrame(animate);
      else prevRef.current = value;
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [value, duration]);
  return <>{display.toLocaleString()}</>;
}

export function KPICard({ label, value, prev, trend, format = "number", icon, sparkline, className, color, onClick }:
  { label: string; value: number; prev?: number; trend?: number; format?: "number" | "percent" | "decimal";
    icon?: React.ReactNode; sparkline?: { value: number }[]; className?: string; color?: string;
    onClick?: () => void }) {
  const trendIcon = trend == null ? null : trend > 0 ? <TrendingUp size={14} className="text-success" /> :
    trend < 0 ? <TrendingDown size={14} className="text-destructive" /> : <Minus size={14} className="text-muted-foreground" />;
  const isUp = trend != null && trend > 0;
  const displayValue = format === "percent" ? `${value}%` :
    format === "decimal" ? value.toFixed(1) : <AnimatedCounter value={value} />;
  const c = color || "hsl(var(--chart-1))";
  return (
    <Card className={cn("relative overflow-hidden transition-all hover:shadow-md cursor-default", className)}
      onClick={onClick} role={onClick ? "button" : undefined}>
      <div className="p-5">
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <div className="text-xs text-muted-foreground truncate mb-1">{label}</div>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold tracking-tight" style={{ color }}>{displayValue}</span>
              {trend != null && (
                <span className={cn("flex items-center gap-0.5 text-xs font-medium", isUp ? "text-success" : "text-destructive")}>
                  {trendIcon}
                  {Math.abs(trend).toFixed(1)}%
                </span>
              )}
            </div>
            {prev != null && <div className="mt-1 text-[11px] text-muted-foreground">prev {prev.toLocaleString()}</div>}
          </div>
          {icon && <div className="text-primary/60 shrink-0 ml-3">{icon}</div>}
        </div>
        {sparkline && sparkline.length > 1 && (
          <div className="mt-2 -mb-3 -mx-2 opacity-60">
            <SparklineChart data={sparkline} dataKey="value" color={c} height={36} width={999} />
          </div>
        )}
      </div>
    </Card>
  );
}
