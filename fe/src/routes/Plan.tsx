import { useQuery } from "@tanstack/react-query";
import { Async, Empty } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { Badge } from "@/components/ui/primitives";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/services/api";

function PlanCard({ p }: { p: any }) {
  const bp = p.blueprint || {};
  const lines: string[] = [];
  if (bp.posts_planned) lines.push(`${bp.posts_planned} posts planned`);
  if (bp.posting_windows?.length)
    lines.push("Windows (IST): " + bp.posting_windows.map((w: any) => `${w.part} ${w.hours}→${w.posts}`).join(", "));
  if (bp.recommended_posts_per_day_during_event)
    lines.push(`Event ramp: ${bp.baseline_posts_per_day} → ${bp.recommended_posts_per_day_during_event} posts/day`);
  if (bp.deal_type_allocation?.length)
    lines.push("Allocation: " + bp.deal_type_allocation.map((a: any) => `${a.deal_type} ×${a.target_posts}`).join(", "));
  if (p.expected_outcome?.estimated_daily_views)
    lines.push(`Est. daily reach: ~${p.expected_outcome.estimated_daily_views} views`);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Badge variant="primary">{p.plan_type}</Badge>
          <CardTitle className="text-base">{p.title}</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-1.5 text-sm">
        {lines.map((l, i) => (
          <div key={i}>{l}</div>
        ))}
        {(p.risks || []).map((r: any, i: number) => (
          <div key={`r${i}`} className="text-warning">⚠ {r.detail}</div>
        ))}
      </CardContent>
    </Card>
  );
}

export function Plan() {
  const q = useQuery({ queryKey: ["plans"], queryFn: () => api.get<any[]>("/api/plans") });
  return (
    <div>
      <PageHeader title="Plan" sub="Daily / weekly / event plans from your growth blueprint + the India sale calendar. Plans only — no publishing." />
      <Async q={q}>
        {(plans) =>
          plans.length ? (
            <div className="grid gap-4">
              {plans.map((p, i) => (
                <PlanCard key={i} p={p} />
              ))}
            </div>
          ) : (
            <Empty>No campaign plans — run the pipeline (includes planning).</Empty>
          )
        }
      </Async>
    </div>
  );
}
