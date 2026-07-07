"use client";

import { useMemo } from "react";
import { Async } from "@/components/Async";
import { BarsChart, MultiLineChart, TimelineChart } from "@/components/charts";
import { StatCard } from "@/components/StatCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DateFilter } from "@/components/ui/date-range-picker";
import { useAnalytics, useCompetitorDashboard, useDataRange } from "@/queries/queries";
import { useQueryParams } from "@/lib/use-search-params";

function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}
function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${Math.round(n)}%`;
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

function toISO(d?: Date): string | undefined {
  return d ? d.toISOString().slice(0, 10) : undefined;
}
function minusDays(iso: string, days: number): string {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

export default function AnalyticsPage() {
  const range = useDataRange();
  const min = range.data?.min ?? undefined;
  const max = range.data?.max ?? undefined;

  const { get, set } = useQueryParams();
  const preset = get("preset", "90d");
  const startParam = get("start", "");
  const endParam = get("end", "");

  const { start, end } = useMemo(() => {
    if (preset === "custom") return { start: startParam || undefined, end: endParam || undefined };
    if (!max || !min) return { start: undefined, end: undefined };
    if (preset === "all") return { start: min, end: max };
    const days: Record<string, number> = { "7d": 7, "30d": 30, "90d": 90 };
    const d = days[preset] ?? 30;
    return { start: minusDays(max, d), end: max };
  }, [preset, min, max, startParam, endParam]);

  const q = useAnalytics(start, end, { enabled: !!range.data });
  const compQ = useCompetitorDashboard(
    preset === "all" || preset === "custom" ? undefined : Number(preset.replace("d", "")),
  );

  const handlePresetChange = (p: string) => {
    const val = p === "custom" ? "90d" : p;
    set({ preset: val, start: null, end: null });
  };

  const handleRangeChange = (from: string, to: string) => {
    set({ preset: "custom", start: from, end: to });
  };

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>
        <p className="text-sm text-muted-foreground">
          Views, reactions, forwards, engagement, CTA, and growth — all from the data we collect.
        </p>
      </div>

      <Card className="mb-4">
        <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
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
        </CardContent>
      </Card>

      <Async q={q} rows={2}>
        {(a) => {
          const win = a.window;
          if (a.total_posts === 0) {
            return (
              <Card><CardContent className="p-10 text-center text-sm text-muted-foreground">
                No posts in this date range. Try a wider range or a different window.
              </CardContent></Card>
            );
          }

          return (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-4 xl:grid-cols-7 xl:gap-6">
                <StatCard label="Posts" value={fmtNum(a.total_posts)} />
                <StatCard label="Views" value={fmtNum(a.total_views)} />
                <StatCard label="Reactions" value={fmtNum(a.total_reactions)} />
                <StatCard label="Forwards" value={fmtNum(a.total_forwards)} />
                <StatCard label="Eng. rate" value={a.engagement_rate != null ? `${a.engagement_rate}%` : "—"} />
                <StatCard label="CTA rate" value={a.cta_rate != null ? `${a.cta_rate}%` : "—"} />
                <StatCard label="Deal rate" value={a.deal_rate != null ? `${a.deal_rate}%` : "—"} />
              </div>

              <ChartCard title="Views & engagement over time"
                sub={`Daily avg views (area) + engagement rate (dashed) · ${win.start || "?"} → ${win.end || "?"}`}>
                <TimelineChart data={a.timeline || []} dataKey="avg_views" unit=" views"
                  secondaryKey="engagement_rate" secondaryUnit="%" />
              </ChartCard>

              {a.growth?.available && (
                <ChartCard title="Subscriber growth" sub="Follower count over time from collection snapshots.">
                  <StatCard
                    label="Subscribers"
                    value={fmtNum(a.growth.current)}
                    trend={{ value: a.growth.growth_rate_pct, label: "vs first snapshot" }}
                  />
                  <div className="mt-3">
                    <TimelineChart
                      data={(a.growth.daily || []).map((d) => ({ label: d.date, count: d.count ?? 0 }))}
                      dataKey="count"
                    />
                  </div>
                </ChartCard>
              )}

              <div className="grid gap-4 lg:grid-cols-2">
                <ChartCard title="Avg views by hour (IST)" sub="All 24 hours — empty slots show 0">
                  <BarsChart data={a.by_hour || []} unit=" views" dataKey="avg_views" />
                </ChartCard>
                <ChartCard title="Avg views by weekday (IST)" sub="Within the selected range">
                  <BarsChart data={a.by_weekday || []} unit=" views" dataKey="avg_views" />
                </ChartCard>
              </div>

              <Async q={compQ} rows={2}>
                {(cd) => {
                  const all = [...(cd.platform ?? []), ...(cd.channel ?? [])];
                  if (all.length < 1) return null;

                  const hourly = Array.from({ length: 24 }, (_, h) => {
                    const row: any = { label: `${String(h).padStart(2, "0")}` };
                    if (a.by_hour?.[h]) row["Your channel"] = a.by_hour[h].avg_views;
                    all.forEach((e: any) => { row[e.name] = e.posts_per_hour_ist?.[h] ?? 0; });
                    return row;
                  });
                  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
                  const wd = days.map((d) => {
                    const row: any = { label: d };
                    row["Your channel"] = a.by_weekday?.find((x: any) => x.label === d)?.avg_views ?? 0;
                    all.forEach((e: any) => { row[e.name] = e.weekday_distribution?.[d] ?? 0; });
                    return row;
                  });

                  const series = [{ key: "Your channel", name: "Your channel" }, ...all.map((e: any) => ({ key: e.name, name: e.name }))];

                  return (
                    <div className="grid gap-4 lg:grid-cols-2">
                      <ChartCard title="Posting by hour (IST) — vs competitors" sub="Your channel vs competitors (post frequency)">
                        <MultiLineChart data={hourly} series={series} unit=" posts" height={220} />
                      </ChartCard>
                      <ChartCard title="Posting by weekday — vs competitors" sub="Your distribution vs all tracked competitors">
                        <MultiLineChart data={wd} series={series} unit=" posts" height={220} />
                      </ChartCard>
                    </div>
                  );
                }}
              </Async>

              <div className="grid gap-6 lg:grid-cols-3">
                <Card className="flex flex-col">
                  <CardHeader>
                    <div className="h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50 mb-3" />
                    <CardTitle className="text-base font-semibold">Golden hours</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm flex-1">
                    <p className="text-xs text-muted-foreground mb-3">Top hours by total engagement (reactions + forwards)</p>
                    {(a.golden_hours?.by_engagement ?? []).length ? (
                      <div className="flex flex-wrap gap-2">
                        {a.golden_hours.by_engagement.map((gh) => (
                          <span key={gh.hour} className="rounded-lg bg-primary/10 px-3 py-1.5 text-sm font-semibold">
                            {gh.hour}
                            <span className="ml-1.5 font-normal text-muted-foreground">{fmtNum(gh.total_engagement)} eng.</span>
                          </span>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">—</p>
                    )}
                    {(a.golden_hours?.by_views ?? []).length > 0 && (
                      <>
                        <p className="text-xs text-muted-foreground mt-3">By views</p>
                        <div className="flex flex-wrap gap-2">
                          {a.golden_hours.by_views.slice(0, 5).map((gh) => (
                            <span key={gh.hour} className="rounded-md bg-muted px-2.5 py-1 text-xs">
                              {gh.hour} · {fmtNum(gh.total_views)} views
                            </span>
                          ))}
                        </div>
                      </>
                    )}
                  </CardContent>
                </Card>

                <Card className="flex flex-col">
                  <CardHeader>
                    <div className="h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50 mb-3" />
                    <CardTitle className="text-base font-semibold">Content signals</CardTitle>
                  </CardHeader>
                  <CardContent className="flex-1 flex flex-col gap-3">
                    <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2">
                      <span className="text-sm text-muted-foreground">CTA rate</span>
                      <span className="text-sm font-semibold">{fmtPct(a.cta_rate ?? 0)}</span>
                    </div>
                    <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2">
                      <span className="text-sm text-muted-foreground">Deal rate</span>
                      <span className="text-sm font-semibold">{fmtPct(a.deal_rate ?? 0)}</span>
                    </div>
                    <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2">
                      <span className="text-sm text-muted-foreground">Engagement rate</span>
                      <span className="text-sm font-semibold">{a.engagement_rate != null ? `${a.engagement_rate}%` : "—"}</span>
                    </div>
                    <div className="border-t pt-3 mt-auto">
                      <p className="mb-1.5 text-xs text-muted-foreground">Avg per post</p>
                      <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2">
                        <span className="text-sm text-muted-foreground">Views</span>
                        <span className="text-sm font-semibold">
                          {a.total_posts ? fmtNum(Math.round(a.total_views / a.total_posts)) : "—"}
                        </span>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                <Card className="flex flex-col">
                  <CardHeader>
                    <div className="h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50 mb-3" />
                    <CardTitle className="text-base font-semibold">Subscriber growth</CardTitle>
                  </CardHeader>
                  <CardContent className="flex-1 space-y-3">
                    {a.growth?.available ? (
                      <>
                        <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2">
                          <span className="text-sm text-muted-foreground">Current</span>
                          <span className="text-sm font-semibold">{fmtNum(a.growth.current)}</span>
                        </div>
                        <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2">
                          <span className="text-sm text-muted-foreground">Growth rate</span>
                          <span className="text-sm font-semibold">{a.growth.growth_rate_pct != null ? fmtPct(a.growth.growth_rate_pct) : "—"}</span>
                        </div>
                        <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2">
                          <span className="text-sm text-muted-foreground">Subs/day</span>
                          <span className="text-sm font-semibold">
                            {a.growth.growth_per_day != null
                              ? `${a.growth.growth_per_day > 0 ? "+" : ""}${a.growth.growth_per_day.toFixed(1)}`
                              : "—"}
                          </span>
                        </div>
                        <div className="pt-2 text-xs text-muted-foreground">
                          {a.growth.first_date?.slice(0, 10)} → {a.growth.last_date?.slice(0, 10)}
                        </div>
                      </>
                    ) : (
                      <p className="text-sm text-muted-foreground">{a.growth?.reason}</p>
                    )}
                  </CardContent>
                </Card>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <ChartCard title="Avg reactions by hour (IST)" sub="How reactions distribute across the day">
                  <BarsChart data={a.by_hour || []} unit=" reactions" dataKey="avg_reactions" />
                </ChartCard>
                <ChartCard title="Avg forwards by hour (IST)" sub="How forwards distribute across the day">
                  <BarsChart data={a.by_hour || []} unit=" forwards" dataKey="avg_forwards" />
                </ChartCard>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <ChartCard title="Avg views by post type" sub="Which formats perform best">
                  <BarsChart data={a.by_type || []} unit=" views" height={280} />
                </ChartCard>
                <ChartCard title="Avg views by merchant (top 10)" sub="Resolved merchants only">
                  <BarsChart data={a.by_merchant || []} unit=" views" height={280} />
                </ChartCard>
              </div>

              <p className="text-xs text-muted-foreground text-center">
                {win.n} posts · {win.days} days · {win.start} → {win.end}
              </p>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
