"use client";

import Link from "next/link";
import { CheckCircle2, XCircle, ExternalLink, FileText, Send, Users, BarChart3, Target } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatCard } from "@/components/StatCard";
import { CalloutCard } from "@/components/CalloutCard";
import { Async } from "@/components/Async";
import { TimelineChart } from "@/components/charts";
import { useOverview, useGrowth, useCompetitorDashboard, useInsights, useDrafts, useQueue } from "@/queries/queries";
import type { OverviewResponse, GrowthRecommendation } from "@/types/api";

function QueueStats({ queue_counts }: { queue_counts: Record<string, number> }) {
  return (
    <div className="flex flex-wrap gap-1">
      {Object.entries(queue_counts).map(([status, count]) => (
        <Badge key={status} variant="secondary">{status}: {count}</Badge>
      ))}
    </div>
  );
}

function PriorityCard({ rec }: { rec: GrowthRecommendation }) {
  return (
    <CalloutCard severity="info" title={rec.recommendation} className="border-l-primary">
      <Badge variant="outline" className="mb-1">{rec.category}</Badge>
      <p className="mt-1 text-sm text-muted-foreground">{rec.reasoning}</p>
    </CalloutCard>
  );
}

export default function OverviewPage() {
  const overview = useOverview();
  const growth = useGrowth();
  const competitors = useCompetitorDashboard();
  const insights = useInsights();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Overview</h1>
        <p className="text-sm text-muted-foreground">Dashboard overview of your channel performance and activities.</p>
      </div>

      <Async q={overview} rows={2}>
        {(data: OverviewResponse) => (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="Posts collected" value={data.posts.toLocaleString()} icon={<FileText className="h-4 w-4" />} />
              <StatCard label="Competitors tracked" value={data.competitors.toLocaleString()} icon={<Users className="h-4 w-4" />} />
              <StatCard label="Drafts ready" value={data.drafts.toLocaleString()} icon={<Send className="h-4 w-4" />} />
              <StatCard label="Queued" value={Object.values(data.queue_counts).reduce((a, b) => a + b, 0).toLocaleString()} sub={<QueueStats queue_counts={data.queue_counts} />} icon={<BarChart3 className="h-4 w-4" />} />
            </div>

            <div className="grid gap-6 lg:grid-cols-3">
              <Card className="col-span-2">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle>Growth</CardTitle>
                      <CardDescription>Subscriber growth over time</CardDescription>
                    </div>
                    <Link href="/growth" className="text-sm text-primary hover:underline inline-flex items-center gap-1">
                      View details <ExternalLink className="h-3 w-3" />
                    </Link>
                  </div>
                </CardHeader>
                <CardContent>
                  <Async q={growth} rows={4}>
                    {(g) => {
                      if (!g.available) return <p className="text-sm text-muted-foreground">{g.reason}</p>;
                      const chartData = g.daily.map((d) => ({ label: d.date, count: d.count ?? 0 }));
                      return (
                        <div className="space-y-4">
                          <StatCard label="Subscribers" value={g.current.toLocaleString()} trend={{ value: g.growth_rate_pct, label: "growth rate" }} />
                          <TimelineChart data={chartData} dataKey="count" unit="" />
                        </div>
                      );
                    }}
                  </Async>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle>Competitor signals</CardTitle>
                      <CardDescription>Recent threats &amp; opportunities</CardDescription>
                    </div>
                    <Link href="/competitors" className="text-sm text-primary hover:underline inline-flex items-center gap-1">
                      View <ExternalLink className="h-3 w-3" />
                    </Link>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <Async q={competitors} rows={3}>
                    {(c) => {
                      const top = c.signals.slice(0, 2);
                      if (top.length === 0) return <p className="text-sm text-muted-foreground">No signals detected.</p>;
                      return top.map((s, i) => (
                        <CalloutCard
                          key={i}
                          severity={s.type === "threat" ? "warning" : "success"}
                          title={s.description}
                          label={`${s.competitor} · ${s.kind}`}
                        />
                      ));
                    }}
                  </Async>
                </CardContent>
              </Card>
            </div>

            <div className="grid gap-6 lg:grid-cols-3">
              <Card className="border-l-primary col-span-2">
                <CardHeader>
                  <CardTitle>Top priority right now</CardTitle>
                  <CardDescription>Highest-impact recommendation</CardDescription>
                </CardHeader>
                <CardContent>
                  <Async q={insights} rows={3}>
                    {(ins) => {
                      const top = ins.recommendations.toSorted((a, b) => a.priority - b.priority)[0];
                      if (!top) return <p className="text-sm text-muted-foreground">No recommendations yet.</p>;
                      return <PriorityCard rec={top} />;
                    }}
                  </Async>
                </CardContent>
              </Card>

              <DraftsQueueCard />
            </div>

            <PublishingGatesCard gates={data.publishing_gates} />
          </>
        )}
      </Async>
    </div>
  );
}

function DraftsQueueCard() {
  const drafts = useDrafts(1, 1);
  const queue = useQueue(1, 1);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Drafts &amp; queue</CardTitle>
        <CardDescription>Content pipeline overview</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Async q={drafts} rows={1}>
          {(d) => (
            <div className="flex items-center justify-between">
              <span className="text-sm">Drafts</span>
              <Link href="/drafts" className="text-2xl font-bold hover:text-primary">{d.items.length}</Link>
            </div>
          )}
        </Async>
        <Async q={queue} rows={1}>
          {(q) => (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm">Queued</span>
                <Link href="/queue" className="text-2xl font-bold hover:text-primary">{q.items.length}</Link>
              </div>
              <div className="flex flex-wrap gap-1">
                {Object.entries(q.counts).map(([status, count]) => (
                  <Badge key={status} variant="outline">{status}: {count}</Badge>
                ))}
              </div>
            </div>
          )}
        </Async>
      </CardContent>
    </Card>
  );
}

function PublishingGatesCard({ gates }: { gates: OverviewResponse["publishing_gates"] }) {
  if (!gates || gates.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Publishing readiness</CardTitle>
        <CardDescription>Blockers and checks before publishing</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {gates.map((gate) => (
          <div key={gate.name} className="flex items-start gap-3 rounded-lg border p-3">
            <div className="mt-0.5 shrink-0">
              {gate.ok ? (
                <CheckCircle2 className="h-4 w-4 text-success" />
              ) : (
                <XCircle className="h-4 w-4 text-destructive" />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{gate.name}</span>
                <Badge variant={gate.ok ? "success" : "destructive"}>
                  {gate.ok ? "Ready" : "Blocked"}
                </Badge>
              </div>
              {gate.detail && (
                <p className="mt-0.5 text-xs text-muted-foreground">{gate.detail}</p>
              )}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
