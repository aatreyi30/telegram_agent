import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Async, Empty } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { Badge } from "@/components/ui/primitives";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
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
      <CardHeader><CardTitle className="text-base">{p.title}</CardTitle></CardHeader>
      <CardContent className="space-y-1.5 text-sm">
        {lines.map((l, i) => <div key={i}>{l}</div>)}
        {(p.risks || []).map((r: any, i: number) => (
          <div key={`r${i}`} className="text-warning">⚠ {r.detail}</div>
        ))}
      </CardContent>
    </Card>
  );
}

function WeeklyTab() {
  const q = useQuery({ queryKey: ["weekly"], queryFn: () => api.get<any>("/api/weekly") });
  return (
    <Async q={q} rows={2}>
      {(d) =>
        !d.weekly_plan && !d.ai_summary ? (
          <Empty>No weekly report yet — run the agent or the pipeline.</Empty>
        ) : (
          <div className="space-y-4">
            {d.ai_summary && (
              <Card>
                <CardHeader><CardTitle className="text-base">This week — summary</CardTitle></CardHeader>
                <CardContent><pre className="whitespace-pre-wrap text-sm leading-relaxed">{d.ai_summary}</pre></CardContent>
              </Card>
            )}
            {d.weekly_plan && (
              <Card>
                <CardHeader><CardTitle className="text-base">{d.weekly_plan.title}</CardTitle></CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <div><span className="font-medium">Cadence:</span>{" "}
                    {d.weekly_plan.blueprint?.posts_per_day} posts/day · {d.weekly_plan.blueprint?.posts_per_week} posts/week</div>
                  {d.weekly_plan.blueprint?.daily_themes && (
                    <Table>
                      <THead><TR><TH>Day</TH><TH>Date</TH><TH>Theme focus</TH><TH>Posts</TH></TR></THead>
                      <TBody>
                        {d.weekly_plan.blueprint.daily_themes.map((t: any, i: number) => (
                          <TR key={i}>
                            <TD className="font-medium">{t.day}</TD>
                            <TD className="text-muted-foreground">{t.date}</TD>
                            <TD>{t.theme_focus}</TD>
                            <TD>{t.posts_planned}</TD>
                          </TR>
                        ))}
                      </TBody>
                    </Table>
                  )}
                  {d.weekly_plan.blueprint?.upcoming_events?.length > 0 && (
                    <div><span className="font-medium">Upcoming events:</span>{" "}
                      {d.weekly_plan.blueprint.upcoming_events.map((e: any) => `${e.name} (${e.days_away}d)`).join(" · ")}</div>
                  )}
                </CardContent>
              </Card>
            )}
            <p className="text-xs text-muted-foreground">What changed & the full recommendation list live in <b>Insights</b>.</p>
          </div>
        )
      }
    </Async>
  );
}

export function Plan() {
  const [tab, setTab] = useState("daily");
  const q = useQuery({ queryKey: ["plans"], queryFn: () => api.get<any[]>("/api/plans") });

  return (
    <div>
      <PageHeader
        title="Plan"
        sub="What to post and when — built from your growth blueprint + the India sale calendar. Plans only; publishing is scheduled from the queue."
      />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="daily">Daily</TabsTrigger>
          <TabsTrigger value="weekly">Weekly report</TabsTrigger>
          <TabsTrigger value="events">Events</TabsTrigger>
        </TabsList>

        <TabsContent value="daily">
          <Async q={q}>
            {(plans) => {
              const daily = plans.filter((p) => p.plan_type === "daily");
              return daily.length ? daily.map((p, i) => <PlanCard key={i} p={p} />)
                : <Empty>No daily plan — run the agent or pipeline.</Empty>;
            }}
          </Async>
        </TabsContent>

        <TabsContent value="weekly"><WeeklyTab /></TabsContent>

        <TabsContent value="events">
          <Async q={q}>
            {(plans) => {
              const events = plans.filter((p) => p.plan_type === "event");
              return events.length ? <div className="space-y-4">{events.map((p, i) => <PlanCard key={i} p={p} />)}</div>
                : <Empty>No event campaigns in the current window.</Empty>;
            }}
          </Async>
        </TabsContent>
      </Tabs>
    </div>
  );
}
