"use client";

import { useMemo, useState } from "react";
import { Async } from "@/components/Async";
import { BarsChart, MultiLineChart, TimelineChart } from "@/components/charts";
import { StatCard } from "@/components/StatCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DateRangePicker } from "@/components/ui/date-range-picker";
import { useAnalytics, useCompetitorDashboard, useDataRange } from "@/queries/queries";
import type { DateRange } from "@/types/ui";

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
        <CardTitle className="text-base">{title}</CardTitle>
        {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function toDate(iso?: string): Date | undefined {
  return iso ? new Date(iso + "T00:00:00Z") : undefined;
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

  const [preset, setPreset] = useState("90d");
  const [custom, setCustom] = useState<DateRange>({});

  const { start, end } = useMemo(() => {
    if (preset === "custom") {
      return { start: toISO(custom.from) || min, end: toISO(custom.to) || max };
    }
    if (!max || !min) return { start: undefined, end: undefined };
    if (preset === "All" || preset === "all") return { start: min, end: max };
    const days = { "7d": 7, "30d": 30, "90d": 90 }[preset] ?? 30;
    return { start: minusDays(max, days), end: max };
  }, [preset, custom, min, max]);

  const q = useAnalytics(start, end, { enabled: !!range.data });
  const compQ = useCompetitorDashboard(Number(preset.replace("d", "")) || undefined);

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-2xl font-bold tracking-tight">Analytics</h1>
        <p className="text-sm text-muted-foreground">
          Views, reactions, forwards, engagement, CTA, and growth — all from the data we collect.
        </p>
      </div>

      {/* Filter bar with DateRangePicker */}
      <Card className="mb-4">
        <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
          <DateRangePicker
            value={preset === "custom" ? custom : { from: toDate(start), to: toDate(end) }}
            onChange={(r) => { setCustom(r); setPreset("custom"); }}
            minDate={toDate(min)}
            maxDate={toDate(max)}
            activePreset={preset === "custom" ? undefined : preset}
            onPresetChange={setPreset}
          />
          <div className="text-xs text-muted-foreground">
            {start && end ? `${start} → ${end}` : "…"}{max ? ` · data to ${max}` : ""}
          </div>
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
              {/* ---- Stat cards ---- */}
              <div className="grid gap-4 sm:grid-cols-4 xl:grid-cols-7">
                <StatCard label="Posts" value={fmtNum(a.total_posts)} />
                <StatCard label="Views" value={fmtNum(a.total_views)} />
                <StatCard label="Reactions" value={fmtNum(a.total_reactions)} />
                <StatCard label="Forwards" value={fmtNum(a.total_forwards)} />
                <StatCard label="Eng. rate" value={a.engagement_rate != null ? `${a.engagement_rate}%` : "—"} />
                <StatCard label="CTA rate" value={a.cta_rate != null ? `${a.cta_rate}%` : "—"} />
                <StatCard label="Deal rate" value={a.deal_rate != null ? `${a.deal_rate}%` : "—"} />
              </div>

              {/* ---- Timeline: avg views + engagement rate overlay ---- */}
              <ChartCard title="Views & engagement over time"
                sub={`Daily avg views (area) + engagement rate (dashed) · ${win.start || "?"} → ${win.end || "?"}`}>
                <TimelineChart data={a.timeline || []} dataKey="avg_views" unit=" views"
                  secondaryKey="engagement_rate" secondaryUnit="%" />
              </ChartCard>

              {/* ---- Growth section ---- */}
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

              {/* ---- Hourly (all 24h) + Weekday ---- */}
              <div className="grid gap-4 lg:grid-cols-2">
                <ChartCard title="Avg views by hour (IST)" sub="All 24 hours — empty slots show 0">
                  <BarsChart data={a.by_hour || []} unit=" views" dataKey="avg_views" />
                </ChartCard>
                <ChartCard title="Avg views by weekday (IST)" sub="Within the selected range">
                  <BarsChart data={a.by_weekday || []} unit=" views" dataKey="avg_views" />
                </ChartCard>
              </div>

              {/* ---- Competitor comparison overlay ---- */}
              <Async q={compQ} rows={2}>
                {(cd) => {
                  const all = [...(cd.platform ?? []), ...(cd.channel ?? [])].slice(0, 3);
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
                    all.forEach((e: any) => { row[e.name] = e.weekday_distribution?.[d] ?? 0; });
                    return row;
                  });

                  const series = all.map((e: any) => ({ key: e.name, name: e.name }));

                  return (
                    <div className="grid gap-4 lg:grid-cols-2">
                      <ChartCard title="Posting by hour (IST) — vs competitors" sub="Solid = your channel, dashed = competitors">
                        <MultiLineChart data={hourly} series={series} unit=" posts" height={220} />
                      </ChartCard>
                      <ChartCard title="Posting by weekday — vs competitors" sub="Your distribution vs top competitors">
                        <MultiLineChart data={wd} series={series} unit=" posts" height={220} />
                      </ChartCard>
                    </div>
                  );
                }}
              </Async>

              {/* ---- Golden hours + Content signals + Growth ---- */}
              <div className="grid gap-4 lg:grid-cols-3">
                <Card>
                  <CardHeader><CardTitle className="text-base">Golden hours</CardTitle></CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    <p className="text-xs text-muted-foreground mb-2">Top hours by total engagement (reactions + forwards)</p>
                    {(a.golden_hours?.by_engagement ?? []).length ? (
                      <div className="flex flex-wrap gap-1.5">
                        {a.golden_hours.by_engagement.map((gh) => (
                          <span key={gh.hour} className="rounded-md bg-primary/10 px-2 py-1 text-xs font-semibold">
                            {gh.hour} · {fmtNum(gh.total_engagement)} eng.
                          </span>
                        ))}
                      </div>
                    ) : <span className="text-muted-foreground">—</span>}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader><CardTitle className="text-base">Content signals</CardTitle></CardHeader>
                  <CardContent className="space-y-3">
                    <StatCard label="CTA rate" value={fmtPct(a.cta_rate ?? 0)} />
                    <StatCard label="Deal rate" value={fmtPct(a.deal_rate ?? 0)} />
                    <StatCard label="Engagement rate" value={a.engagement_rate != null ? `${a.engagement_rate}%` : "—"} />
                    <div className="border-t pt-2">
                      <p className="mb-1 text-xs text-muted-foreground">Avg per post</p>
                      <StatCard
                        label="Views"
                        value={a.total_posts ? fmtNum(Math.round(a.total_views / a.total_posts)) : "—"}
                      />
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader><CardTitle className="text-base">Subscriber growth</CardTitle></CardHeader>
                  <CardContent className="space-y-3">
                    {a.growth?.available ? (
                      <>
                        <StatCard label="Current" value={fmtNum(a.growth.current)} />
                        <StatCard
                          label="Growth rate"
                          value={a.growth.growth_rate_pct != null ? fmtPct(a.growth.growth_rate_pct) : "—"}
                          trend={{ value: a.growth.growth_per_day ?? 0, label: "subs/day" }}
                        />
                        <div className="border-t pt-2 text-xs text-muted-foreground">
                          {a.growth.first_date?.slice(0, 10)} → {a.growth.last_date?.slice(0, 10)}
                        </div>
                      </>
                    ) : (
                      <span className="text-muted-foreground">{a.growth?.reason}</span>
                    )}
                  </CardContent>
                </Card>
              </div>

              {/* ---- Hourly reactions + forwards ---- */}
              <div className="grid gap-4 lg:grid-cols-2">
                <ChartCard title="Avg reactions by hour (IST)" sub="How reactions distribute across the day">
                  <BarsChart data={a.by_hour || []} unit=" reactions" dataKey="avg_reactions" />
                </ChartCard>
                <ChartCard title="Avg forwards by hour (IST)" sub="How forwards distribute across the day">
                  <BarsChart data={a.by_hour || []} unit=" forwards" dataKey="avg_forwards" />
                </ChartCard>
              </div>

              {/* ---- Post type + merchant breakdowns ---- */}
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
