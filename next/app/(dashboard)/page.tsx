"use client";

import Link from "next/link";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  CheckmarkCircle01Icon, Cancel01Icon, ExternalLinkIcon, Note01Icon, Sent02Icon,
  UserGroupIcon, BarChartIcon, Target02Icon, SparklesIcon, ChevronRightIcon,
} from "@hugeicons/core-free-icons";
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
    <div className="flex flex-wrap gap-1.5">
      {Object.entries(queue_counts).map(([status, count]) => (
        <Badge key={status} variant="secondary">{status}: {count}</Badge>
      ))}
    </div>
  );
}

function PriorityCard({ rec }: { rec: GrowthRecommendation }) {
  return (
    <div className="flex items-start gap-3 rounded-lg bg-muted/50 p-3">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary/10">
        <HugeiconsIcon icon={Target02Icon} className="h-4 w-4 text-primary" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs">{rec.category}</Badge>
          {rec.priority != null && <span className="text-xs text-muted-foreground">P{rec.priority}</span>}
        </div>
        <p className="mt-1 text-sm font-medium leading-snug">{rec.recommendation}</p>
        <p className="mt-0.5 text-xs text-muted-foreground leading-relaxed">{rec.reasoning}</p>
      </div>
    </div>
  );
}

export default function OverviewPage() {
  const overview = useOverview();
  const growth = useGrowth();
  const competitors = useCompetitorDashboard();
  const insights = useInsights();

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Overview</h1>
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground mt-1.5">
          <HugeiconsIcon icon={SparklesIcon} className="h-3.5 w-3.5 shrink-0" />
          Dashboard overview of your channel performance and activities.
        </p>
      </div>

      <Async q={overview} rows={2}>
        {(data: OverviewResponse) => (
          <>
            <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="Posts collected" value={data.posts.toLocaleString()} icon={<HugeiconsIcon icon={Note01Icon} className="h-4 w-4" />} />
              <StatCard label="Competitors tracked" value={data.competitors.toLocaleString()} icon={<HugeiconsIcon icon={UserGroupIcon} className="h-4 w-4" />} />
              <StatCard label="Drafts ready" value={data.drafts.toLocaleString()} icon={<HugeiconsIcon icon={Sent02Icon} className="h-4 w-4" />} />
              <StatCard label="Queued" value={Object.values(data.queue_counts).reduce((a, b) => a + b, 0).toLocaleString()} sub={<QueueStats queue_counts={data.queue_counts} />} icon={<HugeiconsIcon icon={BarChartIcon} className="h-4 w-4" />} />
            </div>

            <div className="grid gap-6 lg:grid-cols-3">
              <Card className="col-span-2 rounded-xl overflow-hidden">
                <div className="h-1 bg-gradient-to-r from-primary to-primary/30" />
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle>Growth</CardTitle>
                      <CardDescription>Subscriber growth over time</CardDescription>
                    </div>
                    <Link href="/growth" className="text-sm text-primary hover:underline inline-flex items-center gap-1">
                      View details <HugeiconsIcon icon={ExternalLinkIcon} className="h-3 w-3" />
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

              <Card className="rounded-xl">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle>Competitor signals</CardTitle>
                      <CardDescription>Recent threats &amp; opportunities</CardDescription>
                    </div>
                    <Link href="/competitors" className="text-sm text-primary hover:underline inline-flex items-center gap-1">
                      View <HugeiconsIcon icon={ExternalLinkIcon} className="h-3 w-3" />
                    </Link>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
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

            <div className="grid gap-6 lg:grid-cols-4">
              <Card className="col-span-3 rounded-xl">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle>Now playing</CardTitle>
                      <CardDescription>Top recommendation &amp; pipeline health</CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <Async q={insights} rows={2}>
                    {(ins) => {
                      const top = ins.recommendations.toSorted((a, b) => a.priority - b.priority)[0];
                      if (!top) return <p className="text-sm text-muted-foreground">No recommendations yet.</p>;
                      return <PriorityCard rec={top} />;
                    }}
                  </Async>
                  <Link href="/insights" className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
                    See all recommendations <HugeiconsIcon icon={ChevronRightIcon} className="h-3 w-3" />
                  </Link>
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
    <Card className="rounded-xl">
      <CardHeader>
        <CardTitle>Drafts &amp; queue</CardTitle>
        <CardDescription>Content pipeline overview</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <Async q={drafts} rows={1}>
          {(d) => (
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">Drafts</span>
              <Link href="/drafts" className="flex items-center gap-2 text-2xl font-bold tabular-nums hover:text-primary transition-colors">
                {d.items.length}
                <Badge variant="secondary" className="text-xs font-normal">{d.items.length > 0 ? "pending" : "empty"}</Badge>
              </Link>
            </div>
          )}
        </Async>
        <Async q={queue} rows={1}>
          {(q) => (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">Queued</span>
                <Link href="/queue" className="flex items-center gap-2 text-2xl font-bold tabular-nums hover:text-primary transition-colors">
                  {q.items.length}
                  <Badge variant="secondary" className="text-xs font-normal">{q.items.length > 0 ? "waiting" : "empty"}</Badge>
                </Link>
              </div>
              <div className="flex flex-wrap gap-1.5">
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
  const okCount = gates.filter((g) => g.ok).length;
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-muted/20 p-3">
      <div className="flex items-center gap-2">
        <div className={`h-2 w-2 rounded-full ${okCount === gates.length ? "bg-green-500" : "bg-orange-400"}`} />
        <span className="text-xs font-medium">Publishing readiness</span>
        <Badge variant="outline" className="text-xs">{okCount}/{gates.length} passed</Badge>
      </div>
      <div className="flex flex-wrap gap-2">
        {gates.map((gate) => (
          <div key={gate.name}
            className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs ${
              gate.ok ? "bg-green-50 text-green-700" : "bg-orange-50 text-orange-700"
            }`}
            title={gate.detail || gate.name}
          >
            {gate.ok ? (
              <HugeiconsIcon icon={CheckmarkCircle01Icon} className="h-3 w-3 shrink-0" />
            ) : (
              <HugeiconsIcon icon={Cancel01Icon} className="h-3 w-3 shrink-0" />
            )}
            {gate.name}
          </div>
        ))}
      </div>
    </div>
  );
}
