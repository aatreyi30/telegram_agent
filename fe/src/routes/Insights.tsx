import { useQuery } from "@tanstack/react-query";
import { Async } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { Badge } from "@/components/ui/primitives";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/services/api";

export function Insights() {
  const q = useQuery({ queryKey: ["insights"], queryFn: () => api.get<any>("/api/insights") });
  return (
    <div>
      <PageHeader
        title="Insights"
        sub="What the data says and why — with the calculation, time window, and sample behind each number."
      />
      <Async q={q}>
        {(d) => (
          <div className="space-y-8">
            {/* Recommendations */}
            <section>
              <h2 className="mb-3 text-lg font-semibold">Recommendations</h2>
              <div className="space-y-3">
                {(d.recommendations || []).map((r: any, i: number) => (
                  <Card key={i} className="border-l-4 border-l-primary">
                    <CardContent className="p-4">
                      <div className="mb-1 flex items-center gap-2">
                        {r.priority != null && <Badge variant="primary">P{r.priority}</Badge>}
                        {r.category && <Badge>{r.category}</Badge>}
                      </div>
                      <p className="font-medium">{r.recommendation}</p>
                      {r.reasoning && <p className="mt-1 text-sm text-muted-foreground">{r.reasoning}</p>}
                      {r.expected_outcome && (
                        <p className="mt-1 text-sm text-muted-foreground">Expected: {r.expected_outcome}</p>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            </section>

            {/* Emoji policy */}
            {d.emoji_policy?.rules?.length > 0 && (
              <section>
                <h2 className="mb-3 text-lg font-semibold">Emoji policy</h2>
                <Card>
                  <CardContent className="p-4">
                    <p className="mb-3 text-sm text-muted-foreground">
                      Drafts strip the avoid-emojis automatically. Based on {d.emoji_policy.window} ·
                      correlational (these emojis co-occur with your best/worst post types).
                    </p>
                    <Table>
                      <THead>
                        <TR>
                          <TH>Emoji</TH><TH>Policy</TH><TH>Lift vs avg</TH><TH>Views/day</TH><TH>Sample</TH>
                        </TR>
                      </THead>
                      <TBody>
                        {[...d.emoji_policy.rules].sort((a: any, b: any) => b.lift_pct - a.lift_pct).map((r: any) => (
                          <TR key={r.emoji}>
                            <TD className="text-lg">{r.emoji}</TD>
                            <TD>{r.lift_pct >= 0 ? <Badge variant="success">prefer</Badge> : <Badge variant="destructive">avoid</Badge>}</TD>
                            <TD>{r.lift_pct >= 0 ? "+" : ""}{r.lift_pct}%</TD>
                            <TD className="text-muted-foreground">{r.avg_with} vs {r.baseline}</TD>
                            <TD className="text-muted-foreground">{r.sample.toLocaleString()}</TD>
                          </TR>
                        ))}
                      </TBody>
                    </Table>
                  </CardContent>
                </Card>
              </section>
            )}

            {/* What changed & why */}
            <section>
              <h2 className="mb-3 text-lg font-semibold">What changed &amp; why</h2>
              {(d.reasoning || []).length ? (
                <Card>
                  <CardContent className="p-0">
                    <Table>
                      <THead>
                        <TR><TH>Metric</TH><TH>Change</TH><TH>What it means</TH></TR>
                      </THead>
                      <TBody>
                        {d.reasoning.map((i: any, k: number) => (
                          <TR key={k}>
                            <TD className="font-medium">{i.metric}</TD>
                            <TD>{i.direction} {i.change}{i.unit}</TD>
                            <TD>
                              {i.observation}
                              <div className="text-xs text-muted-foreground">{i.why}</div>
                              <div className="mt-0.5 text-xs text-muted-foreground">Period compared: {i.period}</div>
                            </TD>
                          </TR>
                        ))}
                      </TBody>
                    </Table>
                  </CardContent>
                </Card>
              ) : (
                <p className="text-sm text-muted-foreground">No period-over-period shifts detected.</p>
              )}
            </section>

            {/* Performance */}
            <section>
              <h2 className="mb-3 text-lg font-semibold">Post-type performance (age-normalized)</h2>
              <Card>
                <CardContent className="p-0">
                  <Table>
                    <THead>
                      <TR><TH>Rank</TH><TH>Post type</TH><TH>Posts</TH><TH>Share</TH><TH>Views/day</TH></TR>
                    </THead>
                    <TBody>
                      {(d.performance || []).map((p: any) => (
                        <TR key={p.post_type}>
                          <TD>#{p.rank}</TD>
                          <TD>{p.post_type}</TD>
                          <TD>{p.posts}</TD>
                          <TD>{p.share != null ? Math.round(p.share * 100) + "%" : "—"}</TD>
                          <TD>{p.avg_views_per_day != null ? Math.round(p.avg_views_per_day) : "—"}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </CardContent>
              </Card>
            </section>

            {/* Learnings */}
            <section>
              <h2 className="mb-3 text-lg font-semibold">What the channel has learned</h2>
              <div className="space-y-3">
                {(d.learnings || []).map((l: any, i: number) => (
                  <Card key={i} className="border-l-4 border-l-success">
                    <CardContent className="p-4">
                      <Badge>{l.category}</Badge>
                      <p className="mt-2">{l.statement}</p>
                      {l.how_calculated && (
                        <p className="mt-1 text-sm text-muted-foreground">How this is calculated: {l.how_calculated}</p>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            </section>
          </div>
        )}
      </Async>
    </div>
  );
}
