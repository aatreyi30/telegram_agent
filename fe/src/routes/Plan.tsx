import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { Async, Empty } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { CalloutCard } from "@/components/CalloutCard";
import { Badge } from "@/components/ui/primitives";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { usePlans, useWeekly } from "@/queries/queries";
import type { CampaignPlanDTO } from "@/types/api";

function PlanCard({ p }: { p: CampaignPlanDTO }) {
  const bp = (p.blueprint || {}) as Record<string, any>;
  const stats: { label: string; value: string }[] = [];
  if (bp.posts_planned) stats.push({ label: "Posts planned", value: String(bp.posts_planned) });
  if (bp.posting_windows?.length)
    bp.posting_windows.forEach((w: any) => stats.push({ label: `Window (${w.part})`, value: `${w.hours} → ${w.posts} posts` }));
  if (bp.recommended_posts_per_day_during_event)
    stats.push({ label: "Event ramp", value: `${bp.baseline_posts_per_day} → ${bp.recommended_posts_per_day_during_event}/day` });
  if (p.expected_outcome?.estimated_daily_views)
    stats.push({ label: "Est. daily reach", value: `~${p.expected_outcome.estimated_daily_views} views` });

  return (
    <Card>
      <CardHeader><CardTitle className="text-base">{p.title}</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        {stats.length > 0 && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {stats.map((s, i) => (
              <div key={i} className="rounded-md bg-muted/50 px-2.5 py-1.5">
                <p className="text-xs text-muted-foreground">{s.label}</p>
                <p className="font-semibold">{s.value}</p>
              </div>
            ))}
          </div>
        )}
        {(p.risks || []).map((r, i) => (
          <CalloutCard key={`r${i}`} severity="warning" title={r.detail} />
        ))}
      </CardContent>
    </Card>
  );
}

function WeeklyTab() {
  const q = useWeekly();
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
                <CardContent>
                  {(() => {
                    // Try to split the AI summary into labeled sections
                    const labels = ["biggest win", "biggest concern", "what's working", "what to change", "competitor note"];
                    const lower = d.ai_summary!.toLowerCase();
                    const hasSections = labels.some((l) => lower.includes(l));
                    if (hasSections) {
                      const lines = d.ai_summary!.split(/\n+/).filter(Boolean);
                      return (
                        <div className="space-y-3">
                          {lines.map((line, i) => {
                            const colonIdx = line.indexOf(":");
                            if (colonIdx > 0 && colonIdx < 40) {
                              const h = line.slice(0, colonIdx).trim();
                              const rest = line.slice(colonIdx + 1).trim();
                              return (
                                <div key={i}>
                                  <span className="font-semibold">{h}:</span> {rest}
                                </div>
                              );
                            }
                            return <p key={i} className="leading-relaxed">{line}</p>;
                          })}
                        </div>
                      );
                    }
                    return <p className="whitespace-pre-wrap text-sm leading-relaxed">{d.ai_summary}</p>;
                  })()}
                </CardContent>
              </Card>
            )}
            {d.weekly_plan && (() => {
              const bp = (d.weekly_plan.blueprint || {}) as Record<string, any>;
              return (
                <Card>
                  <CardHeader><CardTitle className="text-base">{d.weekly_plan.title}</CardTitle></CardHeader>
                  <CardContent className="space-y-3 text-sm">
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      <div className="rounded-md bg-muted/50 px-2.5 py-1.5">
                        <p className="text-xs text-muted-foreground">Posts/day</p>
                        <p className="font-semibold">{bp.posts_per_day}</p>
                      </div>
                      <div className="rounded-md bg-muted/50 px-2.5 py-1.5">
                        <p className="text-xs text-muted-foreground">Posts/week</p>
                        <p className="font-semibold">{bp.posts_per_week}</p>
                      </div>
                    </div>
                    {bp.daily_themes && (
                      <Table>
                        <THead><TR><TH>Day</TH><TH>Date</TH><TH>Theme focus</TH><TH>Posts</TH></TR></THead>
                        <TBody>
                          {bp.daily_themes.map((t: any, i: number) => (
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
                    {bp.upcoming_events?.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        <span className="text-xs text-muted-foreground">Upcoming events:</span>
                        {bp.upcoming_events.map((e: any) => (
                          <Badge key={e.name} variant="outline">{e.name} ({e.days_away}d)</Badge>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })()}
            <p className="text-xs text-muted-foreground">What changed & the full recommendation list live in <b>Insights</b>.</p>
          </div>
        )
      }
    </Async>
  );
}

export function Plan() {
  const [tab, setTab] = useState("daily");
  const q = usePlans();

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
