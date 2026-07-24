"use client";

import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Async } from "@/components/Async";
import { BarsChart, TimelineChart } from "@/components/charts";
import { StatCard } from "@/components/StatCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DateFilter } from "@/components/ui/date-range-picker";
import { SourceBreakdownSection, hasSourceBreakdown } from "@/components/SourceBreakdown";
import { useAnalytics, useDataRange } from "@/queries/queries";
import { useQueryParams } from "@/lib/use-search-params";
import { postTypeLabel, merchantLabel } from "@/lib/format";
import { CHART_AXIS_COLOR as AXIS, CHART_GRID_COLOR as GRID } from "@/constants/charts";

function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}
// Single source of truth for rate rendering. The backend already rounds rates to
// 1 dp; DON'T round again here (that produced "12.5%" in one card and "13%" in
// another for the same field). Use this everywhere a rate is shown.
function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${n}%`;
}
// "18:00" -> "6 PM", "09:00" -> "9 AM", "00:00" -> "12 AM"
function to12h(hhmm: string): string {
  const h = parseInt(hhmm.slice(0, 2), 10);
  if (Number.isNaN(h)) return hhmm;
  const period = h < 12 ? "AM" : "PM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12} ${period}`;
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
  const preset = get("preset", "7d");
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
        <h1 className="text-xl font-bold tracking-tight">Analytics</h1>
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
              <div className="grid gap-4 sm:grid-cols-4 xl:grid-cols-7">
                <StatCard label="Posts" value={fmtNum(a.total_posts)} />
                <StatCard label="Views" value={fmtNum(a.total_views)} />
                <StatCard label="Total reactions" value={fmtNum(a.total_reactions)} />
                <StatCard label="Total forwards" value={fmtNum(a.total_forwards)} />
                <StatCard label="Eng. rate" value={fmtPct(a.engagement_rate)} />
                <StatCard label="CTA usage" value={fmtPct(a.cta_rate)} />
                <StatCard label="Deal rate" value={fmtPct(a.deal_rate)} />
              </div>

              <ChartCard title="Views & engagement over time"
                sub={`Daily total views (area) + engagement rate (dashed) · hover for post count · ${win.start || "?"} → ${win.end || "?"}`}>
                <TimelineChart data={a.timeline || []} dataKey="total_views" unit=" views"
                  secondaryKey="engagement_rate" secondaryUnit="%" countKey="n" countLabel="Posts" />
              </ChartCard>

              {a.growth?.available && (
                <>
                  <ChartCard title="Subscriber growth" sub="Follower count over time from collection snapshots.">
                    <div className="grid gap-3 sm:grid-cols-4">
                      <StatCard label="Current subscribers" value={fmtNum(a.growth.current)} />
                      <StatCard label="Joined" value={`+${fmtNum(a.growth.joined)}`} />
                      <StatCard label="Left" value={a.growth.left > 0 ? `-${fmtNum(a.growth.left)}` : "0"} />
                      <StatCard label="Net change" value={a.growth.net > 0 ? `+${fmtNum(a.growth.net)}` : fmtNum(a.growth.net)} />
                    </div>
                    <div className="mt-3">
                      <TimelineChart
                        data={(a.growth.daily || []).map((d) => ({ label: d.date, subs_end: d.subs_end ?? 0 }))}
                        dataKey="subs_end"
                      />
                    </div>
                  </ChartCard>

                  {/* Daily change chart — kept as a raw recharts BarChart (not the shared BarsChart) so each
                      bar can be colored green/red by sign; BarsChart only supports a single fill color. */}
                  <ChartCard title="Daily change" sub={`Net subscriber gain/loss per day. Green = gained, red = lost · ${a.growth.days} days with data`}>
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={a.growth.daily} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
                        <XAxis dataKey="date" tick={{ fill: AXIS, fontSize: 10 }} tickLine={false} axisLine={false}
                          minTickGap={60} tickFormatter={(v: string) => v.slice(5)} />
                        <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
                        <Tooltip
                          contentStyle={{ backgroundColor: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          labelStyle={{ color: "hsl(var(--foreground))", fontWeight: 500 }}
                          formatter={(value: number, name: string, props: any) => [
                            `${value >= 0 ? "+" : ""}${value.toLocaleString()} (joined ${props.payload.joined}, left ${props.payload.left})`,
                            "Net",
                          ]}
                        />
                        <Bar dataKey="net" radius={[2, 2, 0, 0]}>
                          {a.growth.daily.map((d, i) => (
                            <Cell key={i} fill={(d?.net || 0) >= 0 ? "hsl(var(--chart-1))" : "hsl(var(--destructive))"} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </ChartCard>

                  {hasSourceBreakdown(a.growth.view_sources, a.growth.follower_sources) && (
                    <ChartCard title="Views & joins by source"
                      sub="Telegram's admin broadcast-stats breakdown — straight from the API, no derived math.">
                      <SourceBreakdownSection viewSources={a.growth.view_sources} followerSources={a.growth.follower_sources} />
                    </ChartCard>
                  )}
                </>
              )}

              <div className="grid gap-4 lg:grid-cols-2">
                <ChartCard title="Total views by hour (IST)" sub="All 24 hours — empty slots show 0 · hover for post count">
                  <BarsChart data={a.by_hour || []} unit=" views" dataKey="total_views" countKey="n" countLabel="Posts" />
                </ChartCard>
                <ChartCard title="Total views by weekday (IST)" sub="Within the selected range · hover for post count">
                  <BarsChart data={a.by_weekday || []} unit=" views" dataKey="total_views" countKey="n" countLabel="Posts" />
                </ChartCard>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <ChartCard title="Posts by hour (IST)" sub="How many posts we publish in each hour of the day · all 24 hours">
                  <BarsChart data={a.by_hour || []} unit=" posts" dataKey="n" countKey="total_views" countLabel="Views" />
                </ChartCard>
              </div>

              <div className="grid gap-4 lg:grid-cols-3">
                <Card className="flex flex-col">
                  <CardHeader>
                    <div className="h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50 mb-3" />
                    <CardTitle className="text-base font-semibold">Best times to post</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3 text-sm flex-1">
                    <p className="text-xs text-muted-foreground">
                      Your strongest posting hours (IST), ranked by median views per post. Only hours with at
                      least 3 posts are eligible, so this is self-auditing — small sample sizes never win.
                    </p>
                    {(a.golden_hours ?? []).length ? (
                      <div className="space-y-1.5">
                        {a.golden_hours.map((gh, i) => (
                          <div key={gh.hour} className="flex items-center gap-2 rounded-lg bg-primary/10 px-3 py-2">
                            {i === 0 && <span className="text-xs">⭐</span>}
                            <span className="text-sm font-semibold text-foreground">{to12h(gh.hour)}</span>
                            <span className="text-xs text-muted-foreground">— good to post</span>
                            <span className="ml-auto text-xs text-muted-foreground">
                              {fmtNum(gh.median_views)} median views · {gh.n} posts
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">Not enough data yet — need at least 3 posts in a single hour slot.</p>
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
                      <span className="text-sm text-muted-foreground">CTA usage <span className="text-[10px] uppercase tracking-wide opacity-60">(% of posts)</span></span>
                      <span className="text-sm font-semibold">{fmtPct(a.cta_rate)}</span>
                    </div>
                    <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2">
                      <span className="text-sm text-muted-foreground">Deal rate</span>
                      <span className="text-sm font-semibold">{fmtPct(a.deal_rate)}</span>
                    </div>
                    <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2">
                      <span className="text-sm text-muted-foreground">Engagement rate</span>
                      <span className="text-sm font-semibold">{fmtPct(a.engagement_rate)}</span>
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
                          <span className="text-sm text-muted-foreground">Joined</span>
                          <span className="text-sm font-semibold">+{fmtNum(a.growth.joined)}</span>
                        </div>
                        <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2">
                          <span className="text-sm text-muted-foreground">Left</span>
                          <span className="text-sm font-semibold">{a.growth.left > 0 ? `-${fmtNum(a.growth.left)}` : "0"}</span>
                        </div>
                        <div className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2">
                          <span className="text-sm text-muted-foreground">Net</span>
                          <span className="text-sm font-semibold">{a.growth.net > 0 ? `+${fmtNum(a.growth.net)}` : fmtNum(a.growth.net)}</span>
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
                <ChartCard title="Total reactions by hour (IST)" sub="How reactions distribute across the day · hover for post count">
                  <BarsChart data={a.by_hour || []} unit=" reactions" dataKey="total_reactions" countKey="n" countLabel="Posts" />
                </ChartCard>
                <ChartCard title="Total forwards by hour (IST)" sub="How forwards distribute across the day · hover for post count">
                  <BarsChart data={a.by_hour || []} unit=" forwards" dataKey="total_forwards" countKey="n" countLabel="Posts" />
                </ChartCard>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <ChartCard title="Total views by post type" sub="Which formats perform best · hover for post count">
                  <BarsChart data={(a.by_type || []).map((r) => ({ ...r, label: postTypeLabel(r.label) }))} unit=" views" dataKey="total_views" countKey="n" countLabel="Posts" height={280} />
                </ChartCard>
                <ChartCard title="Total views by merchant (top 10)" sub="Resolved merchants only · hover for post count">
                  <BarsChart data={(a.by_merchant || []).map((r) => ({ ...r, label: merchantLabel(r.label) }))} unit=" views" dataKey="total_views" countKey="n" countLabel="Posts" height={280} />
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
