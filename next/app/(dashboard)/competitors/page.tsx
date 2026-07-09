"use client";

import { useMemo } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { InformationCircleIcon } from "@hugeicons/core-free-icons";
import { differenceInCalendarDays } from "date-fns";
import { Async, Empty } from "@/components/Async";
import { MultiLineChart, StackedBarsChart } from "@/components/charts";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { StatCard } from "@/components/StatCard";
import { useCompetitorDashboard, useDataRange } from "@/queries/queries";
import type { CompetitorEntity } from "@/types/api";
import { cn } from "@/lib/utils";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DateFilter } from "@/components/ui/date-range-picker";
import { useQueryParams } from "@/lib/use-search-params";

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

function CategoryBadge({ category }: { category?: CompetitorEntity["category"] }) {
  if (category === "platform") return <Badge variant="primary" className="text-[10px] font-normal">Direct</Badge>;
  if (category === "channel") return <Badge variant="outline" className="text-[10px] font-normal">Indirect</Badge>;
  return null;
}

/**
 * "You 2.1/day · Them 5.3/day (+3.2)" — the diff is a plain subtraction (their posts_per_day
 * minus ours), never a ratio of the delta over our own (often small) value. That ratio pattern
 * was removed because dividing by a small "owned" denominator produces misleadingly huge %s.
 */
function PostsPerDayCell({ e }: { e: CompetitorEntity }) {
  const theirs = e.posts_per_day;
  if (theirs == null) return <span className="text-muted-foreground">—</span>;
  const bench = (e.benchmarks ?? []).find((b) => b.dimension === "posts_per_day");
  const yours = bench?.owned_value;
  const delta = bench?.delta;
  return (
    <span className="text-xs whitespace-nowrap">
      {yours != null && <span className="text-muted-foreground">You {yours.toFixed(1)}/day · </span>}
      <span>Them {theirs.toFixed(1)}/day</span>
      {delta != null && (
        <span
          className={cn(
            "ml-1 font-medium",
            delta > 0 ? "text-emerald-600" : delta < 0 ? "text-red-600" : "text-muted-foreground",
          )}
        >
          ({delta >= 0 ? "+" : ""}{delta.toFixed(1)})
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
                  <span className="truncate">{e.name}</span>
                  <CategoryBadge category={e.category} />
                </div>
              </TableCell>
              <TableCell>{fmtCompact(e.subscribers)}</TableCell>
              <TableCell><PostsPerDayCell e={e} /></TableCell>
              <TableCell>{fmtNum(e.posts)}</TableCell>
              <TableCell>{fmtNum(e.avg_views_per_post)}</TableCell>
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
        <h1 className="text-2xl font-bold tracking-tight">Competitor dashboard</h1>
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
          const dealKeys = dealTypes.map((t) => ({ key: t, name: t }));

          return (
            <div className="space-y-4">
              <div className="grid gap-6 sm:grid-cols-3">
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
            </div>
          );
        }}
      </Async>
    </div>
  );
}
