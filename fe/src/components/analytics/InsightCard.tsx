import { Lightbulb, Sparkles, Bot } from "lucide-react";
import { Card } from "@/components/ui/card";

export function InsightCard({ insights, icon: Icon = Lightbulb, title = "AI Insights", accent = true }:
  { insights: string[]; icon?: any; title?: string; accent?: boolean }) {
  if (!insights?.length) return null;
  return (
    <Card className={`overflow-hidden ${accent ? "border-primary/20 bg-primary/[0.03]" : ""}`}>
      <div className="flex items-center gap-2.5 border-b border-border/50 px-5 py-3">
        <div className="grid h-7 w-7 place-items-center rounded-lg bg-primary/10">
          <Icon size={15} className="text-primary" />
        </div>
        <span className="text-xs font-semibold text-foreground">{title}</span>
      </div>
      <div className="space-y-2.5 px-5 py-4">
        {insights.map((ins, i) => (
          <p key={i} className="flex items-start gap-2.5 text-xs leading-relaxed text-muted-foreground">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary/60" />
            {ins}
          </p>
        ))}
      </div>
    </Card>
  );
}
