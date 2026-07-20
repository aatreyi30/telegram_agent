"use client";

import Link from "next/link";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  CheckmarkCircle01Icon, Cancel01Icon, ExternalLinkIcon, Note01Icon, Sent02Icon,
  UserGroupIcon, BarChartIcon, Target02Icon, ChevronRightIcon,
} from "@hugeicons/core-free-icons";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatCard } from "@/components/StatCard";
import { PageHeader } from "@/components/PageHeader";
import { StatusCounts } from "@/components/StatusPill";
import { Async } from "@/components/Async";
import { TimelineChart } from "@/components/charts";
import { SourceBreakdownSection, hasSourceBreakdown } from "@/components/SourceBreakdown";
import { useOverview, useGrowth, useInsights, useDrafts, useQueue } from "@/queries/queries";
import { titleCase, istDate } from "@/lib/format";
import type { OverviewResponse, GrowthRecommendation, GrowthDailyPoint } from "@/types/api";

function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}

// Period-over-period delta for a numeric field in a `daily` series: splits the series
// into an older half and an equally-sized most-recent half and compares them. Requires
// no new backend data — reuses the daily rows the Growth card already fetched. Returns
// null (no trend rendered) when there isn't enough history for a meaningful comparison,
// or the older window is exactly 0 (a percentage delta would be undefined/fabricated).
function periodTrend(daily: GrowthDailyPoint[], key: "subs_end" | "joined" | "left" | "net", mode: "sum" | "avg" = "sum"): { value: number } | null {
  const n = daily.length;
  if (n < 4) return null;
  const half = Math.floor(n / 2);
  const older = daily.slice(0, half);
  const recent = daily.slice(n - half);
  const aggregate = (rows: GrowthDailyPoint[]) => {
    const sum = rows.reduce((acc, d) => acc + (key === "subs_end" ? d.subs_end ?? 0 : d[key]), 0);
    return mode === "avg" ? sum / rows.length : sum;
  };
  const olderVal = aggregate(older);
  const recentVal = aggregate(recent);
  if (olderVal === 0) return null;
  const pct = ((recentVal - olderVal) / Math.abs(olderVal)) * 100;
  return { value: Math.round(pct * 10) / 10 };
}

function ChannelHeader({ channel }: { channel: OverviewResponse["channel"] }) {
  if (!channel?.available) return null;
  const initial = (channel.title ?? channel.username ?? "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <div className="flex items-center gap-3 rounded-xl border bg-card p-4">
      <div className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-primary/10 text-base font-semibold text-primary">
        {initial}
      </div>
      <div className="min-w-0">
        <p className="truncate text-base font-semibold leading-tight">{channel.title ?? "Untitled channel"}</p>
        <p className="mt-0.5 flex flex-wrap items-center gap-1.5 truncate text-sm text-muted-foreground">
          {channel.username && <span>@{channel.username}</span>}
          {channel.username && channel.subscribers != null && <span aria-hidden>·</span>}
          {channel.subscribers != null && (
            <span className="inline-flex items-center gap-1">
              <HugeiconsIcon icon={UserGroupIcon} className="h-3.5 w-3.5" />
              {channel.subscribers.toLocaleString()} subscribers
            </span>
          )}
        </p>
      </div>
    </div>
  );
}

function QueueStats({ queue_counts }: { queue_counts: Record<string, number> }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      <StatusCounts counts={queue_counts} />
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
          <Badge variant="outline" className="text-xs">{titleCase(rec.category)}</Badge>
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
  const insights = useInsights();

  return (
    <div className="space-y-6">
      <PageHeader title="Overview" subtitle="Your channel at a glance — growth, what to do next, and what's in the pipeline." />

      <Async q={overview} rows={2}>
        {(data: OverviewResponse) => (
          <>
            <ChannelHeader channel={data.channel} />

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="Posts collected" value={data.posts.toLocaleString()} icon={<HugeiconsIcon icon={Note01Icon} className="h-4 w-4" />} />
              <StatCard label="Competitors tracked" value={data.competitors.toLocaleString()} icon={<HugeiconsIcon icon={UserGroupIcon} className="h-4 w-4" />} />
              <StatCard label="Drafts ready" value={data.drafts.toLocaleString()} icon={<HugeiconsIcon icon={Sent02Icon} className="h-4 w-4" />} />
              <StatCard label="Queued" value={Object.values(data.queue_counts).reduce((a, b) => a + b, 0).toLocaleString()} sub={<QueueStats queue_counts={data.queue_counts} />} icon={<HugeiconsIcon icon={BarChartIcon} className="h-4 w-4" />} />
            </div>

            <Card className="rounded-xl overflow-hidden">
              <div className="h-1 bg-gradient-to-r from-primary to-primary/30" />
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>Growth</CardTitle>
                    <CardDescription>Subscriber growth over time</CardDescription>
                  </div>
                  <Link href="/analytics" className="text-sm text-primary hover:underline inline-flex items-center gap-1">
                    View details <HugeiconsIcon icon={ExternalLinkIcon} className="h-3 w-3" />
                  </Link>
                </div>
              </CardHeader>
              <CardContent>
                <Async q={growth} rows={4}>
                  {(g) => {
                    if (!g.available) return <p className="text-sm text-muted-foreground">{g.reason}</p>;
                    const chartData = g.daily.map((d) => ({ label: istDate(d.date), subs_end: d.subs_end ?? 0 }));
                    const churnData = g.daily.map((d) => ({ label: istDate(d.date), joined: d.joined, left: d.left }));
                    const subsTrend = periodTrend(g.daily, "subs_end", "avg");
                    const joinedTrend = periodTrend(g.daily, "joined", "sum");
                    const netTrend = periodTrend(g.daily, "net", "sum");
                    return (
                      <div className="space-y-4">
                        <div className="grid grid-cols-3 gap-3">
                          <StatCard label="Subscribers" value={fmtNum(g.current)}
                            trend={subsTrend ? { ...subsTrend, label: "vs prior period" } : undefined} />
                          <StatCard label="Joined" value={`+${fmtNum(g.joined)}`}
                            trend={joinedTrend ? { ...joinedTrend, label: "vs prior period" } : undefined} />
                          <StatCard label="Net" value={g.net > 0 ? `+${fmtNum(g.net)}` : fmtNum(g.net)}
                            trend={netTrend ? { ...netTrend, label: "vs prior period" } : undefined} />
                        </div>
                        <TimelineChart data={chartData} dataKey="subs_end" unit="" />
                        <div>
                          <p className="mb-1 text-xs font-medium text-muted-foreground">Joined vs left</p>
                          <TimelineChart data={churnData} dataKey="joined" secondaryKey="left" unit="" secondaryUnit="" />
                        </div>
                        {hasSourceBreakdown(g.view_sources, g.follower_sources) && (
                          <div className="border-t pt-4">
                            <SourceBreakdownSection viewSources={g.view_sources} followerSources={g.follower_sources} />
                          </div>
                        )}
                      </div>
                    );
                  }}
                </Async>
              </CardContent>
            </Card>

            <div className="grid gap-4 lg:grid-cols-4">
              <Card className="col-span-3 rounded-xl">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle>Now playing</CardTitle>
                      <CardDescription>Top recommendations &amp; pipeline health</CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <Async q={insights} rows={2}>
                    {(ins) => {
                      const top = ins.recommendations.toSorted((a, b) => a.priority - b.priority).slice(0, 3);
                      if (top.length === 0) return <p className="text-sm text-muted-foreground">No recommendations yet.</p>;
                      return (
                        <div className="space-y-2">
                          {top.map((rec, i) => <PriorityCard key={i} rec={rec} />)}
                        </div>
                      );
                    }}
                  </Async>
                  <Link href="/plan" className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
                    See today's plan <HugeiconsIcon icon={ChevronRightIcon} className="h-3 w-3" />
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
                {d.total}
                <Badge variant="secondary" className="text-xs font-normal">{d.total > 0 ? "ready" : "empty"}</Badge>
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
                  {q.total}
                  <Badge variant="secondary" className="text-xs font-normal">{q.total > 0 ? "waiting" : "empty"}</Badge>
                </Link>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <StatusCounts counts={q.counts} />
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
  const allOk = okCount === gates.length;
  return (
    <Card className="rounded-xl">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <div className={`h-2 w-2 rounded-full ${allOk ? "bg-green-500" : "bg-orange-400"}`} />
          <CardTitle className="text-base">Publishing readiness</CardTitle>
          <Badge variant={allOk ? "success" : "warning"} className="text-xs">{okCount}/{gates.length} ready</Badge>
        </div>
        <CardDescription>{allOk ? "Everything's set — posts can go out." : "A couple of things are blocking posts from sending."}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2 sm:grid-cols-2">
        {gates.map((gate) => (
          <div key={gate.name} className="flex items-start gap-2 rounded-md border bg-muted/20 px-3 py-2 text-sm">
            {gate.ok ? (
              <HugeiconsIcon icon={CheckmarkCircle01Icon} className="mt-0.5 h-4 w-4 shrink-0 text-green-600" />
            ) : (
              <HugeiconsIcon icon={Cancel01Icon} className="mt-0.5 h-4 w-4 shrink-0 text-orange-500" />
            )}
            <div className="min-w-0">
              <p className="font-medium leading-tight">{titleCase(gate.name)}</p>
              {gate.detail && <p className="mt-0.5 text-xs text-muted-foreground leading-relaxed">{gate.detail}</p>}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
