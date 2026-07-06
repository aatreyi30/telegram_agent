import { useQuery } from "@tanstack/react-query";
import { Async, Empty } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { Badge } from "@/components/ui/primitives";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/services/api";

export function Weekly() {
  const q = useQuery({ queryKey: ["weekly"], queryFn: () => api.get<any>("/api/weekly") });
  return (
    <div>
      <PageHeader
        title="Weekly report"
        sub="Your week at a glance — the plan for the next 7 days, what changed vs the prior period, the top moves to make, and a plain-language summary."
      />
      <Async q={q} rows={3}>
        {(d) =>
          !d.available && !d.ai_summary ? (
            <Empty>No weekly report yet — run the pipeline or the agent to generate one.</Empty>
          ) : (
            <div className="space-y-4">
              {d.ai_summary && (
                <Card>
                  <CardHeader><CardTitle className="text-base">This week — summary</CardTitle></CardHeader>
                  <CardContent>
                    <pre className="whitespace-pre-wrap text-sm leading-relaxed">{d.ai_summary}</pre>
                  </CardContent>
                </Card>
              )}

              {d.weekly_plan && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">{d.weekly_plan.title}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3 text-sm">
                    <div>
                      <span className="font-medium">Cadence:</span>{" "}
                      {d.weekly_plan.blueprint?.posts_per_day} posts/day ·{" "}
                      {d.weekly_plan.blueprint?.posts_per_week} posts/week
                    </div>
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
                      <div>
                        <span className="font-medium">Upcoming events:</span>{" "}
                        {d.weekly_plan.blueprint.upcoming_events.map((e: any) =>
                          `${e.name} (${e.days_away}d, ${e.date_confidence})`).join(" · ")}
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}

              <Card>
                <CardHeader><CardTitle className="text-base">What changed</CardTitle></CardHeader>
                <CardContent className="p-0">
                  {(d.what_changed || []).length ? (
                    <Table>
                      <THead><TR><TH>Metric</TH><TH>Change</TH><TH>Why</TH></TR></THead>
                      <TBody>
                        {d.what_changed.map((i: any, k: number) => (
                          <TR key={k}>
                            <TD className="font-medium">{i.metric}</TD>
                            <TD>{i.direction} {i.change}{i.unit}</TD>
                            <TD className="text-muted-foreground">{i.why}<div className="text-xs">Period: {i.period}</div></TD>
                          </TR>
                        ))}
                      </TBody>
                    </Table>
                  ) : (
                    <p className="p-4 text-sm text-muted-foreground">No notable shifts this period.</p>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader><CardTitle className="text-base">Top moves this week</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  {(d.recommendations || []).map((r: any, i: number) => (
                    <div key={i} className="border-b pb-2 last:border-0 last:pb-0">
                      <div className="flex items-center gap-2">
                        {r.priority != null && <Badge variant="primary">P{r.priority}</Badge>}
                        <span className="text-sm font-medium">{r.recommendation}</span>
                      </div>
                      {r.reasoning && <div className="mt-0.5 text-xs text-muted-foreground">{r.reasoning}</div>}
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>
          )
        }
      </Async>
    </div>
  );
}
