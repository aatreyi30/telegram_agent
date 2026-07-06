import { useState, useRef, ReactNode } from "react";
import { Download, Expand, Lightbulb, ChevronDown, ChevronUp } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function ChartCard({ title, sub, metric, children, insights, className, id, onExpand, onDownload }:
  { title: string; sub?: string; metric?: string; children: ReactNode; insights?: string[];
    className?: string; id?: string; onExpand?: () => void; onDownload?: () => void }) {
  const [showInsights, setShowInsights] = useState(false);
  return (
    <Card className={cn("overflow-hidden", className)} id={id}>
      <div className="flex items-start justify-between gap-4 p-5 pb-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-foreground truncate">{title}</h3>
          {sub && <p className="mt-0.5 text-xs text-muted-foreground truncate">{sub}</p>}
          {metric && <p className="mt-1.5 text-2xl font-bold tracking-tight">{metric}</p>}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {onDownload && (
            <button onClick={onDownload} title="Download chart data"
              className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors">
              <Download size={14} />
            </button>
          )}
          {onExpand && (
            <button onClick={onExpand} title="Expand"
              className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors">
              <Expand size={14} />
            </button>
          )}
        </div>
      </div>
      <CardContent className="p-5 pt-0">{children}</CardContent>
      {insights && insights.length > 0 && (
        <div className="border-t border-border/50">
          <button onClick={() => setShowInsights(!showInsights)}
            className="flex w-full items-center gap-2 px-5 py-2.5 text-xs text-muted-foreground hover:text-foreground transition-colors">
            <Lightbulb size={13} className="text-warning shrink-0" />
            <span>{insights.length} AI insight{insights.length > 1 ? "s" : ""}</span>
            {showInsights ? <ChevronUp size={14} className="ml-auto" /> : <ChevronDown size={14} className="ml-auto" />}
          </button>
          {showInsights && (
            <div className="space-y-1.5 px-5 pb-4">
              {insights.map((ins, i) => (
                <p key={i} className="flex items-start gap-2 text-xs text-muted-foreground">
                  <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                  {ins}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
