"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { HugeiconsIcon } from "@hugeicons/react";
import { ArrowLeft01Icon } from "@hugeicons/core-free-icons";
import { Async, Empty } from "@/components/Async";
import { CategoryBadge } from "@/components/CategoryBadge";
import { BarsChart, StackedBarsChart, TimelineChart } from "@/components/charts";
import { StatCard } from "@/components/StatCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCompetitorDashboard, useCompetitorTrends } from "@/queries/queries";
import { useQueryParams } from "@/lib/use-search-params";
import type { CompetitorBenchmarkRow, CompetitorEntity } from "@/types/api";
import { cn } from "@/lib/utils";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}

/** Compact K/M formatting for large counts like subscribers — same convention as the table page. */
function fmtCompact(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const trim = (s: string) => (s.endsWith(".0") ? s.slice(0, -2) : s);
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${trim((n / 1_000_000).toFixed(1))}M`;
  if (abs >= 1_000) return `${trim((n / 1_000).toFixed(1))}K`;
  return n.toLocaleString();
}

function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${Math.round(n)}%`;
}

// Humanize a raw dataKey/dimension ("avg_views_per_post" -> "Avg views per post") for legible labels.
function humanize(key?: string): string {
  if (!key) return "";
  const s = key.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Reads the first present key from `candidates`, falling back to the first non-date numeric key. */
function pickKey(rows: any[] | undefined, candidates: string[]): string | undefined {
  if (!rows?.length) return undefined;
  const row = rows[0];
  for (const c of candidates) if (typeof row[c] === "number") return c;
  return Object.keys(row).find((k) => k !== "date" && typeof row[k] === "number");
}

/** Reads the first present key from `candidates` on a single object, else undefined. */
function pick<T = any>(o: any, candidates: string[]): T | undefined {
  if (!o) return undefined;
  for (const c of candidates) if (o[c] != null) return o[c];
  return undefined;
}

// The chart wrapper components (BarsChart/TimelineChart/StackedBarsChart) all key their X axis
// off a "label" field — day-bucketed trend rows key off "date" instead, so normalize here.
function labelize(rows: any[] | undefined): any[] {
  return (rows ?? []).map((r) => ({ ...r, label: r.date ?? r.label ?? r.bucket ?? "" }));
}

/** All numeric fields present across a set of day-bucketed rows (excluding the date/label), for stacked charts. */
function numericSeriesKeys(rows: any[] | undefined, exclude: string[] = ["date"]): { key: string; name: string }[] {
  const keys = new Set<string>();
  (rows ?? []).forEach((r) => {
    Object.keys(r).forEach((k) => { if (!exclude.includes(k) && typeof r[k] === "number") keys.add(k); });
  });
  return Array.from(keys).map((k) => ({ key: k, name: humanize(k) }));
}

function ChartCard({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <div className="h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50 mb-3" />
        <CardTitle className="text-base font-semibold">{title}</CardTitle>
        {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

/**
 * Single-row CSS-grid heat strip — colors cells by intensity relative to the row's max.
 * Used for both the by-hour (24 cells) and by-weekday (7 cells) posting-time views. We don't
 * render a true hour x weekday grid because the backend only exposes the two marginal
 * distributions (hour_distribution_ist, weekday_distribution), not a joint one — combining them
 * via an outer product would fabricate a joint pattern that isn't actually observed.
 */
function HeatStrip({ cells }: { cells: { label: string; value: number }[] }) {
  const max = Math.max(1, ...cells.map((c) => c.value));
  return (
    <div className="flex gap-1">
      {cells.map((c) => {
        const intensity = c.value / max;
        return (
          <div key={c.label} className="min-w-0 flex-1 text-center" title={`${c.label}: ${fmtNum(c.value)} posts`}>
            <div className="h-8 rounded" style={{ backgroundColor: `hsl(var(--primary) / ${(0.08 + intensity * 0.82).toFixed(2)})` }} />
            <div className="mt-1 truncate text-[10px] text-muted-foreground">{c.label}</div>
          </div>
        );
      })}
    </div>
  );
}

function BenchmarksList({ benchmarks }: { benchmarks: CompetitorBenchmarkRow[] }) {
  if (!benchmarks?.length) return <p className="text-sm text-muted-foreground">No benchmark data yet.</p>;
  return (
    <div className="space-y-1.5">
      {benchmarks.map((b) => (
        <div key={b.dimension} className="flex items-center justify-between gap-2 rounded-lg bg-muted/50 px-3 py-2 text-sm">
          <span className="truncate text-muted-foreground">{humanize(b.dimension)}</span>
          <span className="flex shrink-0 items-center gap-2 whitespace-nowrap text-xs">
            {b.owned_value != null && <span className="text-muted-foreground">You {fmtNum(b.owned_value)}</span>}
            {b.competitor_value != null && <span className="font-medium text-foreground">Them {fmtNum(b.competitor_value)}</span>}
            {b.delta != null && (
              <span className={cn("font-semibold", b.delta > 0 ? "text-emerald-600" : b.delta < 0 ? "text-red-600" : "text-muted-foreground")}>
                ({b.delta >= 0 ? "+" : ""}{fmtNum(Math.round(b.delta * 100) / 100)})
              </span>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}

function MerchantShareList({ mix }: { mix?: Record<string, number> }) {
  const entries = Object.entries(mix ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 10);
  if (!entries.length) return <p className="text-sm text-muted-foreground">No merchant data yet.</p>;
  const max = Math.max(...entries.map(([, v]) => v));
  return (
    <div className="space-y-2.5">
      {entries.map(([name, v]) => (
        <div key={name} className="space-y-1">
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="truncate font-medium">{name}</span>
            <span className="shrink-0 text-muted-foreground">{fmtNum(v)}</span>
          </div>
          <div className="h-2 rounded-full bg-muted">
            <div className="h-2 rounded-full bg-primary" style={{ width: `${max ? (v / max) * 100 : 0}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function CompetitorDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);

  const dashboard = useCompetitorDashboard(); // no window -> full/lifetime mode, needed for hour/weekday distributions
  const { get, set } = useQueryParams();
  const days = Number(get("days", "30")) || 30;
  const trends = useCompetitorTrends(id, days);

  const entity = useMemo<CompetitorEntity | undefined>(() => {
    if (!dashboard.data) return undefined;
    return [...(dashboard.data.platform ?? []), ...(dashboard.data.channel ?? [])].find((e) => e.id === id);
  }, [dashboard.data, id]);

  const handleDaysChange = (v: string) => set({ days: v === "30" ? null : v });

  return (
    <div className="space-y-4">
      <Link href="/competitors" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <HugeiconsIcon icon={ArrowLeft01Icon} className="h-4 w-4" />
        Back to competitors
      </Link>

      <Async q={dashboard} rows={2}>
        {() => {
          if (!entity) return <Empty>Competitor not found. It may have been removed, or hasn't been assigned an id yet.</Empty>;

          const hourCells = Array.from({ length: 24 }, (_, h) => ({
            label: String(h).padStart(2, "0"), value: entity.posts_per_hour_ist?.[h] ?? 0,
          }));
          const weekdayCells = WEEKDAYS.map((day) => ({ label: day, value: entity.weekday_distribution?.[day] ?? 0 }));

          return (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-2xl font-bold tracking-tight">{entity.name}</h1>
                <CategoryBadge category={entity.category} />
              </div>

              <div className="grid gap-4 sm:grid-cols-4">
                <StatCard label="Subscribers" value={fmtCompact(entity.subscribers)} />
                <StatCard label="Posts/day" value={entity.posts_per_day != null ? entity.posts_per_day.toFixed(1) : "—"} />
                <StatCard label="Avg views/post" value={fmtNum(entity.avg_views_per_post)} />
                <StatCard label="Merchant coverage" value={entity.merchant_coverage != null ? fmtPct(entity.merchant_coverage * 100) : "—"} />
              </div>

              <ChartCard title="Posting time patterns (IST)" sub="Marginal distributions — hour and weekday shown separately (no joint data available)">
                <div className="space-y-5">
                  <div>
                    <p className="mb-2 text-xs font-medium text-muted-foreground">By hour</p>
                    <HeatStrip cells={hourCells} />
                  </div>
                  <div>
                    <p className="mb-2 text-xs font-medium text-muted-foreground">By weekday</p>
                    <HeatStrip cells={weekdayCells} />
                  </div>
                </div>
              </ChartCard>

              <div className="grid gap-4 lg:grid-cols-2">
                <ChartCard title="Vs. your channel" sub="Benchmark deltas — positive means the competitor leads.">
                  <BenchmarksList benchmarks={entity.benchmarks ?? []} />
                </ChartCard>
                <ChartCard title="Merchant share" sub="Top 10 merchants by share of posts.">
                  <MerchantShareList mix={entity.merchant_mix} />
                </ChartCard>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
                <h2 className="text-lg font-semibold tracking-tight">Trends</h2>
                <Tabs value={String(days)} onValueChange={handleDaysChange}>
                  <TabsList>
                    <TabsTrigger value="7">7d</TabsTrigger>
                    <TabsTrigger value="30">30d</TabsTrigger>
                    <TabsTrigger value="90">90d</TabsTrigger>
                  </TabsList>
                </Tabs>
              </div>

              <Async q={trends} rows={2}>
                {(t) => {
                  const postingData = labelize(t.posting_trend);
                  const postingKey = pickKey(t.posting_trend, ["posts", "post_count", "count", "n"]) ?? "posts";
                  const viewsData = labelize(t.views_trend);
                  const viewsKey = pickKey(t.views_trend, ["views", "total_views", "avg_views"]) ?? "views";
                  const linkData = labelize(t.link_usage_trend);
                  const linkKey = pickKey(t.link_usage_trend, ["avg_links", "link_rate", "links", "link_usage"]) ?? "avg_links";
                  const captionBuckets = (t.caption_length_distribution ?? []).map((b) => ({
                    label: b.bucket ?? b.label ?? "", count: b.count ?? 0,
                  }));
                  const consistency = t.posting_consistency;
                  const stdev = pick<number>(consistency, ["stdev", "std_dev", "standard_deviation"]);
                  const variance = pick<number>(consistency, ["variance", "var"]);

                  return (
                    <div className="space-y-4">
                      <ChartCard title="Posting trend" sub={`Posts per day over the last ${days} days.`}>
                        <div className="space-y-3">
                          <TimelineChart data={postingData} dataKey={postingKey} unit=" posts" />
                          {(stdev != null || variance != null) && (
                            <div className="grid gap-3 sm:grid-cols-2">
                              <StatCard label="Posting consistency (stdev)" value={stdev != null ? stdev.toFixed(2) : "—"} />
                              <StatCard label="Variance" value={variance != null ? variance.toFixed(2) : "—"} />
                            </div>
                          )}
                        </div>
                      </ChartCard>

                      <ChartCard title="Daily posting frequency" sub="Same series as above, as a bar count per day.">
                        <BarsChart data={postingData} dataKey={postingKey} unit=" posts" />
                      </ChartCard>

                      <ChartCard title="Views trend" sub={`Views per day over the last ${days} days.`}>
                        <TimelineChart data={viewsData} dataKey={viewsKey} unit=" views" />
                      </ChartCard>

                      <div className="grid gap-4 lg:grid-cols-2">
                        <ChartCard title="Content mix trend" sub="Post-type share per day.">
                          <StackedBarsChart data={labelize(t.content_mix_trend)} keys={numericSeriesKeys(t.content_mix_trend)} height={240} />
                        </ChartCard>
                        <ChartCard title="Media vs text trend" sub="Media-led vs text-only posts per day.">
                          <StackedBarsChart data={labelize(t.media_text_trend)} keys={numericSeriesKeys(t.media_text_trend)} height={240} />
                        </ChartCard>
                      </div>

                      <ChartCard title="Merchant trend" sub="Merchant share of posts per day.">
                        <StackedBarsChart data={labelize(t.merchant_trend)} keys={numericSeriesKeys(t.merchant_trend)} height={280} />
                      </ChartCard>

                      <div className="grid gap-4 lg:grid-cols-2">
                        <ChartCard title="Link usage trend" sub="Average links per post, per day.">
                          <TimelineChart data={linkData} dataKey={linkKey} unit="" />
                        </ChartCard>
                        <ChartCard title="Caption length distribution" sub="Post count by caption-length bucket.">
                          <BarsChart data={captionBuckets} dataKey="count" unit=" posts" />
                        </ChartCard>
                      </div>

                      <ChartCard title="Top performing posts" sub="Ranked by views.">
                        <div className="overflow-x-auto">
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="w-10">#</TableHead>
                                <TableHead>Caption</TableHead>
                                <TableHead className="text-right">Views</TableHead>
                                <TableHead className="text-right">Forwards</TableHead>
                                <TableHead className="text-right">Reactions</TableHead>
                                <TableHead>Posted</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {(t.top_posts ?? []).map((p, i) => {
                                const views = pick<number>(p, ["views", "total_views"]);
                                const forwards = pick<number>(p, ["forwards", "total_forwards"]);
                                const reactions = pick<number>(p, ["reactions", "total_reactions"]);
                                const caption = pick<string>(p, ["caption", "text", "preview"]);
                                const postedAt = pick<string>(p, ["posted_at", "date", "published_at"]);
                                return (
                                  <TableRow key={p.post_id ?? i} className="hover:bg-muted/50">
                                    <TableCell className="text-muted-foreground">{i + 1}</TableCell>
                                    <TableCell className="max-w-96 truncate" title={caption ?? undefined}>{caption ?? "—"}</TableCell>
                                    <TableCell className="text-right font-semibold">{fmtNum(views)}</TableCell>
                                    <TableCell className="text-right">{fmtNum(forwards)}</TableCell>
                                    <TableCell className="text-right">{fmtNum(reactions)}</TableCell>
                                    <TableCell className="whitespace-nowrap text-muted-foreground">{postedAt ? String(postedAt).slice(0, 10) : "—"}</TableCell>
                                  </TableRow>
                                );
                              })}
                              {(t.top_posts ?? []).length === 0 && (
                                <TableRow>
                                  <TableCell colSpan={6} className="text-center text-sm text-muted-foreground">No posts in this window.</TableCell>
                                </TableRow>
                              )}
                            </TableBody>
                          </Table>
                        </div>
                      </ChartCard>
                    </div>
                  );
                }}
              </Async>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
