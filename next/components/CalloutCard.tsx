"use client";

import { ReactNode, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, Info, XCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { CalloutSeverity } from "@/types/ui";

const SEVERITY: Record<CalloutSeverity, {
  border: string; icon: ReactNode; badge: "primary" | "secondary" | "destructive" | "outline";
}> = {
  info: { border: "border-l-primary", icon: <Info className="h-4 w-4" />, badge: "primary" },
  success: { border: "border-l-green-500", icon: <CheckCircle2 className="h-4 w-4" />, badge: "secondary" },
  warning: { border: "border-l-orange-500", icon: <AlertTriangle className="h-4 w-4" />, badge: "outline" },
  danger: { border: "border-l-destructive", icon: <XCircle className="h-4 w-4" />, badge: "destructive" },
};

export function CalloutCard({ severity = "info", label, title, children, evidence, className }: {
  severity?: CalloutSeverity; label?: ReactNode; title: ReactNode; children?: ReactNode; evidence?: ReactNode; className?: string;
}) {
  const [open, setOpen] = useState(false);
  const s = SEVERITY[severity];
  return (
    <Card className={cn("border-l-4", s.border, className)}>
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 shrink-0 text-muted-foreground">{s.icon}</div>
          <div className="min-w-0 flex-1">
            {label && <Badge variant={s.badge} className="mb-1.5">{label}</Badge>}
            <div className="text-sm font-medium leading-snug text-foreground">{title}</div>
            {children && <div className="mt-1 text-sm text-muted-foreground">{children}</div>}
            {evidence && (
              <div className="mt-2">
                <button type="button" onClick={() => setOpen((o) => !o)}
                  className="flex items-center gap-1 text-xs font-medium text-primary hover:underline">
                  <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
                  {open ? "Hide evidence" : "Show evidence"}
                </button>
                {open && <div className="mt-2 rounded-md bg-muted/50 p-2.5 text-xs text-muted-foreground">{evidence}</div>}
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
