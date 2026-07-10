import { ReactNode, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, Info, XCircle } from "lucide-react";
import { Card, CardContent } from "./ui/card";
import { Badge } from "./ui/primitives";
import { cn } from "@/lib/utils";
import type { CalloutSeverity } from "@/types/ui";

const SEVERITY: Record<CalloutSeverity, {
  border: string;
  icon: ReactNode;
  badge: "primary" | "success" | "warning" | "destructive";
}> = {
  info: { border: "border-l-primary", icon: <Info className="h-4 w-4" />, badge: "primary" },
  success: { border: "border-l-success", icon: <CheckCircle2 className="h-4 w-4" />, badge: "success" },
  warning: { border: "border-l-warning", icon: <AlertTriangle className="h-4 w-4" />, badge: "warning" },
  danger: { border: "border-l-destructive", icon: <XCircle className="h-4 w-4" />, badge: "destructive" },
};

/** Consolidates the "border-l-4 + badge + paragraph" pattern that was previously
 * copy-pasted across Insights (recommendations, learnings) and CompetitorDashboard
 * (signals). `evidence`, if given, renders as a collapsed-by-default disclosure so
 * a card can lead with the recommendation/observation and let the underlying data
 * stay one click away instead of doubling the card's length by default. */
export function CalloutCard({ severity = "info", label, title, children, evidence, className }: {
  severity?: CalloutSeverity;
  label?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  evidence?: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const s = SEVERITY[severity];
  return (
    <Card className={cn("border-l-4", s.border, className)}>
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 shrink-0 text-muted-foreground">{s.icon}</div>
          <div className="min-w-0 flex-1">
            {label && (
              <Badge variant={s.badge} className="mb-1.5">
                {label}
              </Badge>
            )}
            <div className="text-sm font-medium leading-snug text-foreground">{title}</div>
            {children && <div className="mt-1 text-sm text-muted-foreground">{children}</div>}
            {evidence && (
              <div className="mt-2">
                <button
                  type="button"
                  onClick={() => setOpen((o) => !o)}
                  className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                >
                  <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
                  {open ? "Hide evidence" : "Show evidence"}
                </button>
                {open && (
                  <div className="mt-2 rounded-md bg-muted/50 p-2.5 text-xs text-muted-foreground">
                    {evidence}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
