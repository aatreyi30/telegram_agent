"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  CheckmarkCircle01Icon, Cancel01Icon, ExternalLinkIcon, Note01Icon, Sent02Icon,
  UserGroupIcon, BarChartIcon, Target02Icon, ChevronRightIcon,
} from "@hugeicons/core-free-icons";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog } from "@/components/ui/dialog";
import { StatCard } from "@/components/StatCard";
import { LivePulse } from "@/components/LivePulse";
import { PageHeader } from "@/components/PageHeader";
import { StatusCounts } from "@/components/StatusPill";
import { Async } from "@/components/Async";
import { TimelineChart } from "@/components/charts";
import { SourceBreakdownSection, hasSourceBreakdown } from "@/components/SourceBreakdown";
import { useOverview, useGrowth, useInsights, useDrafts, useQueue, useActivity } from "@/queries/queries";
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
// the older window is exactly 0 (a percentage delta would be undefined/fabricated), OR
// any row in play spans a multi-day collection gap — that row's total isn't one day's
// activity, so a row-count-based "older half vs recent half" split would compare a real
// period against a gap-inflated one and produce a wildly bogus %.
function periodTrend(daily: GrowthDailyPoint[], key: "subs_end" | "joined" | "left" | "net", mode: "sum" | "avg" = "sum"): { value: number } | null {
  const n = daily.length;
  if (n < 4) return null;
  if (daily.some((d) => d.spans_days > 1)) return null;
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

/** True when the agent has actually done something in the last 10 minutes —
 * the honest signal behind the "Live" pulse, not a decorative always-on dot. */
function useAgentIsLive(): boolean {
  const activity = useActivity(1);
  const at = activity.data?.events?.[0]?.at;
  if (!at) return false;
  return Date.now() - new Date(at).getTime() < 10 * 60 * 1000;
}

function ChannelHeader({ channel }: { channel: OverviewResponse["channel"] }) {
  const live = useAgentIsLive();
  if (!channel?.available) return null;
  const initial = (channel.title ?? channel.username ?? "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <div className="relative overflow-hidden flex items-center gap-3 rounded-xl border border-primary/15 bg-gradient-to-r from-primary/[0.08] via-card to-card p-4">
      <div className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-gradient-to-br from-primary to-primary/60 text-base font-semibold text-primary-foreground shadow-sm">
        {initial}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="truncate text-base font-semibold leading-tight">{channel.title ?? "Untitled channel"}</p>
          <LivePulse label={live ? "Agent live" : "Agent idle"} active={live} />
        </div>
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

const DIGEST_SESSION_KEY = "dw_digest_shown";

/** A dismissible "what happened since you were last here" pop-up — real counts
 * from the same activity feed the toast stream uses, framed as a summary instead
 * of a live stream. Shows once per browser session (sessionStorage-gated), and
 * only if something actually happened — an empty digest isn't worth a pop-up. */
function SessionDigest() {
  const activity = useActivity(50);
  const growth = useGrowth();
  const [open, setOpen] = useState(false);
  const decided = useRef(false);

  useEffect(() => {
    if (decided.current || !activity.data) return;
    decided.current = true;
    if (typeof window === "undefined" || sessionStorage.getItem(DIGEST_SESSION_KEY)) return;
    const events = activity.data.events;
    const published = events.filter((e) => e.type === "post_published").length;
    const blocked = events.filter((e) => e.type === "post_blocked").length;
    const drafted = events.filter((e) => e.type === "draft_created").length;
    if (published + blocked + drafted === 0) return;
    setOpen(true);
    sessionStorage.setItem(DIGEST_SESSION_KEY, "1");
  }, [activity.data]);

  if (!open || !activity.data) return null;
  const events = activity.data.events;
  const published = events.filter((e) => e.type === "post_published").length;
  const blocked = events.filter((e) => e.type === "post_blocked").length;
  const drafted = events.filter((e) => e.type === "draft_created").length;
  const subsTrend = growth.data?.available ? periodTrend(growth.data.daily, "subs_end", "avg") : null;

  return (
    <Dialog open={open} onClose={() => setOpen(false)} title="Since you were last here">
      <div className="space-y-2 text-sm">
        <p>
          <span className="font-medium">{drafted}</span> post{drafted === 1 ? "" : "s"} drafted,{" "}
          <span className="font-medium">{published}</span> sent
          {blocked > 0 ? <>, <span className="font-medium text-amber-600 dark:text-amber-400">{blocked}</span> blocked</> : ""}.
        </p>
        {subsTrend && (
          <p className="text-muted-foreground">
            Subscribers {subsTrend.value >= 0 ? "up" : "down"} {Math.abs(subsTrend.value)}% vs the prior period.
          </p>
        )}
      </div>
    </Dialog>
  );
}

export default function OverviewPage() {
  const overview = useOverview();
  const growth = useGrowth();
  const insights = useInsights();

  return (
    <div className="space-y-6">
      <SessionDigest />
      <PageHeader title="Overview" subtitle="Your channel at a glance — growth, what to do next, and what's in the pipeline." />

      <Async q={overview} rows={2}>
        {(data: OverviewResponse) => (
          <>
            <ChannelHeader channel={data.channel} />

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard variant="hero" label="Posts collected" value={data.posts.toLocaleString()} icon={<HugeiconsIcon icon={Note01Icon} className="h-5 w-5" />} />
              <StatCard label="Competitors tracked" value={data.competitors.toLocaleString()} icon={<HugeiconsIcon icon={UserGroupIcon} className="h-4 w-4" />} className="[animation-delay:75ms]" />
              <StatCard label="Drafts ready" value={data.drafts.toLocaleString()} icon={<HugeiconsIcon icon={Sent02Icon} className="h-4 w-4" />} className="[animation-delay:150ms]" />
              <StatCard label="Queued" value={Object.values(data.queue_counts).reduce((a, b) => a + b, 0).toLocaleString()} sub={<QueueStats queue_counts={data.queue_counts} />} icon={<HugeiconsIcon icon={BarChartIcon} className="h-4 w-4" />} className="[animation-delay:225ms]" />
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
                    const gapDays = Math.max(1, ...g.daily.map((d) => d.spans_days));
                    const gapNote = `covers ${gapDays} days, not just 1`;
                    return (
                      <div className="space-y-4">
                        {g.has_collection_gap && (
                          <p className="rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                            ⚠ Tracking was paused for {gapDays} days in this window. The Joined/Net numbers
                            below are real, but they're the total for all {gapDays} days combined — not one day's growth.
                          </p>
                        )}
                        <div className="grid grid-cols-3 gap-3">
                          <StatCard label="Subscribers" value={fmtNum(g.current)}
                            trend={subsTrend ? { ...subsTrend, label: "vs prior period" } : undefined} />
                          <StatCard label="Joined" value={`+${fmtNum(g.joined)}`}
                            sub={g.has_collection_gap ? gapNote : undefined}
                            trend={joinedTrend ? { ...joinedTrend, label: "vs prior period" } : undefined} />
                          <StatCard label="Net" value={g.net > 0 ? `+${fmtNum(g.net)}` : fmtNum(g.net)}
                            sub={g.has_collection_gap ? gapNote : undefined}
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
  const queue = useQueue({ page: 1 }, 1);

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
              <Link href="/posts?status=draft" className="flex items-center gap-2 text-2xl font-bold tabular-nums hover:text-primary transition-colors">
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
                <Link href="/posts?status=all" className="flex items-center gap-2 text-2xl font-bold tabular-nums hover:text-primary transition-colors">
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
