import { Link } from "react-router-dom";
import { ArrowRight, CheckCircle2, FileText, Inbox, Radar, Radio, Send, TrendingUp, Users2, XCircle } from "lucide-react";
import { Async, Empty } from "@/components/Async";
import { CalloutCard } from "@/components/CalloutCard";
import { PageHeader } from "@/components/AppLayout";
import { StatCard } from "@/components/StatCard";
import { TimelineChart } from "@/components/charts";
import { Badge } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fmtNum } from "@/lib/utils";
import { useCompetitorDashboard, useGrowth, useInsights, useOverview } from "@/queries/queries";

// Overview is a growth cockpit, not just a link farm: it summarizes the
// follower trend, the top competitor signals, and drafts/queue status inline
// so the operator gets the headline numbers here. Full history/detail still
// lives on Growth, Competitors, Insights, Drafts, and Queue.
export function Overview() {
  const ov = useOverview();
  const ins = useInsights();
  const growth = useGrowth();
  const compDash = useCompetitorDashboard();

  return (
    <div>
      <PageHeader
        title="Overview"
        sub="Your channel at a glance — growth, competitor signals, and the one thing to do next. Full history lives in Growth, Competitors, and Insights."
      />

      <Async q={ov} rows={1}>
        {(o) => {
          const queued = Object.values(o.queue_counts || {}).reduce((a, b) => a + b, 0);
          return (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="posts collected" value={fmtNum(o.posts)} icon={<Radio size={20} />} />
              <StatCard label="competitors tracked" value={fmtNum(o.competitors)} icon={<Users2 size={20} />} />
              <StatCard label="drafts ready" value={fmtNum(o.drafts)} icon={<FileText size={20} />} />
              <StatCard label="queued to post" value={fmtNum(queued)} icon={<Send size={20} />} />
            </div>
          );
        }}
      </Async>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base"><TrendingUp size={16} /> Growth</CardTitle>
            <Link to="/app/growth"><Button variant="ghost" size="sm">Full history <ArrowRight size={14} /></Button></Link>
          </CardHeader>
          <CardContent>
            <Async q={growth} rows={2}>
              {(g) =>
                g.available ? (
                  <div>
                    <StatCard
                      label="subscribers"
                      value={fmtNum(g.current)}
                      trend={{ value: g.growth_rate_pct, label: "vs first snapshot" }}
                    />
                    <div className="mt-4">
                      <TimelineChart
                        data={g.daily.map((d) => ({ label: d.date, count: d.count ?? 0 }))}
                        dataKey="count"
                      />
                    </div>
                  </div>
                ) : (
                  <Empty>Collecting data — follower snapshots accrue every collection cycle.</Empty>
                )
              }
            </Async>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base"><Radar size={16} /> Competitor signals</CardTitle>
            <Link to="/app/competitors"><Button variant="ghost" size="sm">View full comparison <ArrowRight size={14} /></Button></Link>
          </CardHeader>
          <CardContent className="space-y-3">
            <Async q={compDash} rows={2}>
              {(d) => {
                const signals = (d.signals || []).slice(0, 2);
                if (signals.length === 0)
                  return <p className="text-sm text-muted-foreground">No competitor signals yet.</p>;
                return (
                  <>
                    {signals.map((s, i) => (
                      <CalloutCard
                        key={i}
                        severity={s.type === "threat" ? "warning" : "info"}
                        label={s.competitor}
                        title={s.description}
                      >
                        {s.kind}
                      </CalloutCard>
                    ))}
                  </>
                );
              }}
            </Async>
          </CardContent>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="border-l-4 border-l-primary lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-base">Top priority right now</CardTitle>
            <Link to="/app/insights"><Button variant="ghost" size="sm">All insights <ArrowRight size={14} /></Button></Link>
          </CardHeader>
          <CardContent>
            <Async q={ins} rows={1}>
              {(d) => {
                const r = (d.recommendations || [])[0];
                if (!r) return <p className="text-sm text-muted-foreground">No recommendations yet — run the agent.</p>;
                return (
                  <div>
                    <div className="mb-1 flex items-center gap-2">
                      {r.priority != null && <Badge variant="primary">P{r.priority}</Badge>}
                      {r.category && <Badge>{r.category}</Badge>}
                    </div>
                    <p className="font-medium">{r.recommendation}</p>
                    {r.reasoning && <p className="mt-1 text-sm text-muted-foreground">{r.reasoning}</p>}
                  </div>
                );
              }}
            </Async>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base"><Inbox size={16} /> Drafts & queue</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <Async q={ov} rows={1}>
              {(o) => {
                const queueEntries = Object.entries(o.queue_counts || {});
                const queued = queueEntries.reduce((a, [, n]) => a + n, 0);
                return (
                  <>
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Drafts ready</span>
                      <Link to="/app/drafts"><Badge variant="primary">{fmtNum(o.drafts)}</Badge></Link>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Queued (all statuses)</span>
                      <Link to="/app/queue"><Badge>{fmtNum(queued)}</Badge></Link>
                    </div>
                    {queueEntries.length > 0 && (
                      <div className="flex flex-wrap gap-1 pt-1">
                        {queueEntries.map(([status, n]) => (
                          <Badge key={status} className="font-normal">{status}: {n}</Badge>
                        ))}
                      </div>
                    )}
                    <div className="flex gap-2 pt-2">
                      <Link to="/app/drafts"><Button variant="ghost" size="sm">Drafts <ArrowRight size={14} /></Button></Link>
                      <Link to="/app/queue"><Button variant="ghost" size="sm">Queue <ArrowRight size={14} /></Button></Link>
                    </div>
                  </>
                );
              }}
            </Async>
          </CardContent>
        </Card>
      </div>

      <Async q={ov} rows={1}>
        {(o) => (
          <Card className="mt-4">
            <CardHeader><CardTitle className="text-base">Publishing readiness</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {(o.publishing_gates || []).map((g, i) => (
                <div key={i} className="flex items-start gap-3 border-b pb-3 last:border-0 last:pb-0">
                  {g.ok ? <CheckCircle2 className="mt-0.5 shrink-0 text-success" size={18} />
                        : <XCircle className="mt-0.5 shrink-0 text-destructive" size={18} />}
                  <div>
                    <div className="flex items-center gap-2 text-sm font-medium">
                      {g.name} {g.ok ? <Badge variant="success">ready</Badge> : <Badge variant="destructive">blocked</Badge>}
                    </div>
                    <p className="text-xs text-muted-foreground">{g.detail}</p>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        )}
      </Async>
    </div>
  );
}
