"use client";

import { useMemo } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { InformationCircleIcon } from "@hugeicons/core-free-icons";
import { differenceInCalendarDays } from "date-fns";
import { Async, Empty } from "@/components/Async";
import { CategoryBadge } from "@/components/CategoryBadge";
import { BarsChart, MultiLineChart, StackedBarsChart } from "@/components/charts";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { StatCard } from "@/components/StatCard";
import { useCompetitorDashboard, useCompetitorDashboardTrends, useDataRange } from "@/queries/queries";
import type { CompetitorEntity } from "@/types/api";
import { cn } from "@/lib/utils";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DateFilter } from "@/components/ui/date-range-picker";
import { useQueryParams } from "@/lib/use-search-params";
import { postTypeLabel, merchantLabel, categoryLabel, istDate } from "@/lib/format";
import type { DealGapRow, DimensionCoverage } from "@/types/api";

function minusDays(iso: string, days: number): string {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}

/** Compact K/M formatting for large counts like subscribers — plain, no false precision. */
function fmtCompact(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const trim = (s: string) => (s.endsWith(".0") ? s.slice(0, -2) : s);
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${trim((n / 1_000_000).toFixed(1))}M`;
  if (abs >= 1_000) return `${trim((n / 1_000).toFixed(1))}K`;
  return n.toLocaleString();
}

// deal_gap shares/gap are fractions (0-1) from the backend, unlike the rest of this
// page's already-percent fields — convert here, at the point of display.
function fmtShare(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${Math.round(n * 1000) / 10}%`;
}

// "categorized 118 of 375 posts (31%)" — the two sides of a deal-gap comparison are
// categorized at different rates (category is matched from each post's own text, and
// competitor posts are often sparsely-captioned forwards, so fewer of them hit a category
// keyword than owned posts' fuller copy), so the gap is not like-for-like unless both
// coverages are stated. Guards total === 0.
function coverageLabel(cov: DimensionCoverage | undefined): string {
  const categorized = cov?.categorized ?? 0;
  const total = cov?.total ?? 0;
  const pct = total > 0 ? Math.round((categorized / total) * 100) : 0;
  return `categorized ${categorized} of ${total} posts (${pct}%)`;
}

function DealGapCard({ rows, windowDays, minN, ownedCoverage, competitorCoverage }: {
  rows: DealGapRow[]; windowDays: number; minN: number;
  ownedCoverage?: DimensionCoverage; competitorCoverage?: DimensionCoverage;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="mb-2 h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50" />
        <CardTitle className="text-base">Deal-gap — what rivals win with that we're absent from</CardTitle>
        <p className="text-xs text-muted-foreground">
          Share of posts per category, us vs tracked competitors, over the last {windowDays} days.
          Only categories with at least {minN} competitor posts are shown.
        </p>
        <p className="text-xs text-muted-foreground">
          Us: {coverageLabel(ownedCoverage)} · Competitors: {coverageLabel(competitorCoverage)} —
          the two sides are categorized at different rates, so this gap is not a clean like-for-like comparison.
        </p>
      </CardHeader>
      <CardContent className="p-0">
        {rows.length ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Category</TableHead>
                  <TableHead>Our share</TableHead>
                  <TableHead>Their share</TableHead>
                  <TableHead>Gap</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.category} className={cn("hover:bg-muted/50", r.over_indexed_by_competitors && "bg-amber-500/10")}>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        <span>{categoryLabel(r.category)}</span>
                        {r.over_indexed_by_competitors && (
                          <Badge variant="warning" className="text-[10px] font-normal">Competitors over-index</Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="tabular-nums text-xs text-muted-foreground">{fmtShare(r.owned_share)} ({r.owned_n})</TableCell>
                    <TableCell className="tabular-nums text-xs text-muted-foreground">{fmtShare(r.competitor_share)} ({r.competitor_n})</TableCell>
                    <TableCell className={cn("tabular-nums font-medium", r.gap > 0 ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground")}>
                      {r.gap >= 0 ? "+" : ""}{fmtShare(r.gap)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="p-10 text-center text-sm text-muted-foreground">
            Not enough data yet — a category needs at least {minN} competitor posts in this window to show a gap.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * A just-added competitor has no `last_collected_at`-style field on this response yet (the
 * comparison entities below never expose it), so we treat "no posts observed" as a proxy for
 * "collection hasn't run yet". TODO(backend): expose a real `last_collected_at` on
 * CompetitorEntity so this can be exact instead of inferred from posts/posts_per_day.
 */
function ProcessingBadge({ e }: { e: CompetitorEntity }) {
  const hasData = (e.posts ?? 0) > 0 || (e.posts_per_day ?? 0) > 0;
  if (hasData) return null;
  // No posts observed in-window. We can't tell "not collected yet" from "genuinely
  // dormant" (CompetitorEntity has no last_collected_at), so say what's actually true
  // rather than implying it's still loading.
  return <Badge variant="secondary" className="text-[10px] font-normal">No posts in range</Badge>;
}

/**
 * "You 2/day · Them 5/day (+3)" — the diff is a plain subtraction (their posts_per_day
 * minus ours), never a ratio of the delta over our own (often small) value. That ratio pattern
 * was removed because dividing by a small "owned" denominator produces misleadingly huge %s.
 *
 * You / Them / delta ALL come from the benchmark row so they share ONE window and always
 * reconcile (Them − You = delta). The entity's full-span `posts_per_day` is a DIFFERENT
 * window — mixing it in produced rows like "You 38 · Them 212 (+27)" where 38+27≠212.
 * We only fall back to the full-span rate when there's no benchmark (and then show no delta).
 */
function PostsPerDayCell({ e }: { e: CompetitorEntity }) {
  const bench = (e.benchmarks ?? []).find((b) => b.dimension === "posts_per_day");
  const theirs = bench?.competitor_value ?? e.posts_per_day;
  if (theirs == null) return <span className="text-muted-foreground">—</span>;
  const yours = bench?.owned_value;
  // Derive the shown delta from the SHOWN (rounded) You/Them so it always adds up on
  // screen — rounding the raw delta separately left rows like "You 40 · Them 19 (-20)"
  // where 19-40 reads as -21. When there's no owned value, fall back to the raw delta.
  const shownThem = Math.round(theirs);
  const shownYou = yours != null ? Math.round(yours) : null;
  const delta = shownYou != null && bench?.delta != null ? shownThem - shownYou : bench?.delta ?? null;
  return (
    <span className="text-xs whitespace-nowrap">
      {shownYou != null && <span className="text-muted-foreground">You {shownYou}/day · </span>}
      <span>Them {shownThem}/day</span>
      {e.window_mismatch && (
        <span
          className="ml-1 text-amber-600 dark:text-amber-400"
          title="These are computed over very different observation windows (e.g. your months of history vs their few days tracked) — not a like-for-like comparison."
        >
          ⚠
        </span>
      )}
      {delta != null && (
        <span
          className={cn(
            "ml-1 font-medium",
            delta > 0 ? "text-emerald-600" : delta < 0 ? "text-red-600" : "text-muted-foreground",
          )}
        >
          ({delta >= 0 ? "+" : ""}{Math.round(delta)})
        </span>
      )}
    </span>
  );
}

/**
 * Single consolidated competitor table — replaces the old card grid + separate style/behaviour
 * benchmark table. Deliberately drops similarity_to_us, deal-mix badges, and granular style
 * rates (cta/coupon/multi_deal/emoji/hashtag/links/media) from display; the backend may keep
 * computing them, they're just not rendered here.
 */
function CompetitorsTable({ entities }: { entities: CompetitorEntity[] }) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Competitor</TableHead>
            <TableHead>Subscribers</TableHead>
            <TableHead>Posts/day</TableHead>
            <TableHead>Num posts</TableHead>
            <TableHead>
              <span className="inline-flex items-center gap-1">
                Avg views/post
                <Tooltip>
                  <TooltipTrigger asChild>
                    <HugeiconsIcon icon={InformationCircleIcon} className="h-3.5 w-3.5 cursor-help text-muted-foreground" />
                  </TooltipTrigger>
                  <TooltipContent>approx · public view count</TooltipContent>
                </Tooltip>
              </span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {entities.map((e) => (
            <TableRow key={e.name} className="hover:bg-muted/50">
              <TableCell className="font-medium">
                <div className="flex items-center gap-2">
                  <span>{e.name}</span>
                  <CategoryBadge category={e.category} />
                  <ProcessingBadge e={e} />
                </div>
              </TableCell>
              <TableCell className="tabular-nums">{fmtCompact(e.subscribers)}</TableCell>
              <TableCell><PostsPerDayCell e={e} /></TableCell>
              <TableCell className="tabular-nums">{fmtNum(e.posts)}</TableCell>
              <TableCell className="tabular-nums">
                {e.avg_views_reliable === false ? (
                  <span className="text-muted-foreground" title="Views weren't captured reliably for this channel (placeholder/implausible counts), so the average isn't shown.">—</span>
                ) : (
                  fmtNum(e.avg_views_per_post)
                )}
              </TableCell>
            </TableRow>
          ))}
          {entities.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="text-center text-sm text-muted-foreground">
                No competitors in this category.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}

export default function CompetitorDashboardPage() {
  const range = useDataRange();
  const min = range.data?.min ?? undefined;
  const max = range.data?.max ?? undefined;

  const { get, set } = useQueryParams();
  const preset = get("preset", "7d");
  const startParam = get("start", "");
  const endParam = get("end", "");
  const tab = get("tab", "all") as "all" | "platform" | "channel";

  const { window, start, end } = useMemo(() => {
    if (preset === "custom" && startParam && endParam) {
      const days = Math.max(1, differenceInCalendarDays(new Date(endParam), new Date(startParam)) + 1);
      return { window: days, start: startParam, end: endParam };
    }
    if (preset === "all") return { window: undefined, start: min, end: max };
    const days: Record<string, number> = { "7d": 7, "30d": 30, "90d": 90 };
    const d = days[preset] ?? 7;
    return { window: d, start: max ? minusDays(max, d) : undefined, end: max };
  }, [preset, startParam, endParam, min, max]);

  const q = useCompetitorDashboard(window);
  const trendsQ = useCompetitorDashboardTrends(30);

  const setTab = (v: string) => set({ tab: v === "all" ? null : v });

  const handlePresetChange = (p: string) => {
    const val = p === "custom" ? "7d" : p;
    set({ preset: val === "7d" ? null : val, start: null, end: null });
  };

  const handleRangeChange = (from: string, to: string) => {
    set({ preset: "custom", start: from, end: to });
  };

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-xl font-bold tracking-tight">Competitor dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Direct competitors (platform + Telegram) vs Telegram-only channels — all metrics, side by side.
        </p>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <DateFilter
          mode="range"
          preset={preset}
          onPresetChange={handlePresetChange}
          from={start}
          to={end}
          onRangeChange={handleRangeChange}
          min={min}
          max={max}
          showArrows
        />
        <Tabs value={tab} onValueChange={setTab} className="ml-auto">
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="platform">Direct</TabsTrigger>
            <TabsTrigger value="channel">Indirect</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <Async q={q} rows={2}>
        {(d) => {
          if ((d.platform ?? []).length === 0 && (d.channel ?? []).length === 0) {
            return <Empty>No competitor data yet. Run competitor discovery first.</Empty>;
          }

          const rawEntities = [...(d.platform ?? []), ...(d.channel ?? [])];
          const entities = tab === "all" ? rawEntities : rawEntities.filter((e: any) => e.category === tab);

          const allTypes = new Set<string>();
          entities.forEach((e: any) => { if (e.deal_mix) Object.keys(e.deal_mix).forEach((t) => allTypes.add(t)); });
          const dealTypes = Array.from(allTypes);

          const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
          const wdData = days.map((day) => {
            const row: any = { label: day };
            entities.forEach((e: any) => { row[e.name] = e.weekday_distribution?.[day] ?? 0; });
            return row;
          });
          const hourly = Array.from({ length: 24 }, (_, h) => {
            const row: any = { label: `${String(h).padStart(2, "0")}` };
            entities.forEach((e: any) => { row[e.name] = e.posts_per_hour_ist?.[h] ?? 0; });
            return row;
          });

          const weekSeries = entities.map((e: any) => ({ key: e.name, name: e.name }));
          const hourSeries = entities.map((e: any) => ({ key: e.name, name: e.name }));

          const dealData = entities.map((e: any) => {
            const row: any = { label: e.name };
            dealTypes.forEach((t) => { row[t] = e.deal_mix?.[t] ?? 0; });
            return row;
          });
          const dealKeys = dealTypes.map((t) => ({ key: t, name: postTypeLabel(t) }));

          const rankingData = [...entities]
            .sort((a: any, b: any) => (b.posts_per_day ?? 0) - (a.posts_per_day ?? 0))
            .map((e: any) => ({ label: e.name, posts_per_day: Math.round(e.posts_per_day ?? 0) }));

          const coverageData = entities.map((e: any) => ({
            label: e.name, coverage: Math.round((e.merchant_coverage ?? 0) * 1000) / 10,
          }));

          const merchantTotals = new Map<string, number>();
          entities.forEach((e: any) => {
            Object.entries(e.merchant_mix ?? {}).forEach(([m, n]) => {
              merchantTotals.set(m, (merchantTotals.get(m) ?? 0) + (n as number));
            });
          });
          const topMerchants = Array.from(merchantTotals.entries())
            .sort((a, b) => b[1] - a[1]).slice(0, 8).map(([m]) => m);
          const merchantShareData = entities.map((e: any) => {
            const row: any = { label: e.name };
            topMerchants.forEach((m) => { row[m] = e.merchant_mix?.[m] ?? 0; });
            return row;
          });
          const merchantShareKeys = topMerchants.map((m) => ({ key: m, name: merchantLabel(m) }));

          return (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-3">
                <StatCard label="Competitors" value={fmtNum(d.summary?.total ?? 0)} />
                <StatCard label="Direct (platform)" value={fmtNum(d.summary?.platform ?? 0)} />
                <StatCard label="Indirect (Telegram)" value={fmtNum(d.summary?.channel ?? 0)} />
              </div>

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    {tab === "all" ? "All competitors" : tab === "platform" ? "Direct competitors" : "Indirect competitors"}
                    <span className="ml-2 text-sm font-normal text-muted-foreground">{entities.length}</span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-0">
                  <CompetitorsTable entities={entities} />
                </CardContent>
              </Card>

              <DealGapCard rows={d.deal_gap?.rows ?? []} windowDays={d.deal_gap?.window_days ?? 30} minN={d.deal_gap?.min_competitor_n ?? 0}
                ownedCoverage={d.deal_gap?.owned_coverage} competitorCoverage={d.deal_gap?.competitor_coverage} />

              {dealTypes.length > 0 && entities.length >= 2 && (
                <Card>
                  <CardHeader><div className="mb-2 h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50" /><CardTitle className="text-base">Deal-type mix</CardTitle>
                    <p className="text-xs text-muted-foreground">What each competitor emphasises.</p></CardHeader>
                  <CardContent>
                    <StackedBarsChart data={dealData} keys={dealKeys} unit="%" height={260} />
                  </CardContent>
                </Card>
              )}

              {entities.length >= 2 && (
                <div className="grid gap-4 lg:grid-cols-2">
                  <Card>
                    <CardHeader><div className="mb-2 h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50" /><CardTitle className="text-base">Posting by weekday</CardTitle></CardHeader>
                    <CardContent>
                      <MultiLineChart data={wdData} series={weekSeries} unit=" posts" height={220} />
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader><div className="mb-2 h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50" /><CardTitle className="text-base">Posting by hour (IST)</CardTitle></CardHeader>
                    <CardContent>
                      <MultiLineChart data={hourly} series={hourSeries} unit=" posts" height={220} />
                    </CardContent>
                  </Card>
                </div>
              )}

              {entities.length >= 2 && (
                <Card>
                  <CardHeader><div className="mb-2 h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50" /><CardTitle className="text-base">Competitor ranking</CardTitle>
                    <p className="text-xs text-muted-foreground">Ranked by posts/day.</p></CardHeader>
                  <CardContent>
                    <BarsChart data={rankingData} dataKey="posts_per_day" unit="/day" height={260} />
                  </CardContent>
                </Card>
              )}

              {entities.length >= 2 && (
                <div className="grid gap-4 lg:grid-cols-2">
                  <Card>
                    <CardHeader><div className="mb-2 h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50" /><CardTitle className="text-base">Merchant coverage</CardTitle>
                      <p className="text-xs text-muted-foreground">Share of extracted links resolved to a known merchant.</p></CardHeader>
                    <CardContent>
                      <BarsChart data={coverageData} dataKey="coverage" unit="%" height={240} />
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader><div className="mb-2 h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50" /><CardTitle className="text-base">Merchant share by competitor</CardTitle>
                      <p className="text-xs text-muted-foreground">Top 8 merchants overall.</p></CardHeader>
                    <CardContent>
                      <StackedBarsChart data={merchantShareData} keys={merchantShareKeys} height={240} />
                    </CardContent>
                  </Card>
                </div>
              )}

              {trendsQ.data && trendsQ.data.competitors.length >= 2 && (
                <div className="grid gap-4 lg:grid-cols-2">
                  <Card>
                    <CardHeader><div className="mb-2 h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50" /><CardTitle className="text-base">Posting trend (30d)</CardTitle></CardHeader>
                    <CardContent>
                      <MultiLineChart
                        data={trendsQ.data.posting_trend.map((r) => ({ ...r, label: istDate(r.date) }))}
                        series={trendsQ.data.competitors.map((c) => ({ key: c.name, name: c.name }))}
                        unit=" posts" height={240}
                      />
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader><div className="mb-2 h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50" /><CardTitle className="text-base">Views trend (30d)</CardTitle></CardHeader>
                    <CardContent>
                      <MultiLineChart
                        data={trendsQ.data.views_trend.map((r) => ({ ...r, label: istDate(r.date) }))}
                        series={trendsQ.data.competitors.map((c) => ({ key: c.name, name: c.name }))}
                        unit=" views" height={240}
                      />
                    </CardContent>
                  </Card>
                </div>
              )}
            </div>
          );
        }}
      </Async>
    </div>
  );
}
