"use client";

import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { HugeiconsIcon } from "@hugeicons/react";
import { Cancel01Icon } from "@hugeicons/core-free-icons";
import { Async } from "@/components/Async";
import { BarsChart, TimelineChart } from "@/components/charts";
import { DayDetail } from "@/components/DayDetail";
import { StatCard } from "@/components/StatCard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DateFilter } from "@/components/ui/date-range-picker";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SourceBreakdownSection, hasSourceBreakdown } from "@/components/SourceBreakdown";
import { useAnalytics, useDataRange } from "@/queries/queries";
import { useQueryParams } from "@/lib/use-search-params";
import { postTypeLabel, merchantLabel, categoryLabel, titleCase, isoSlash } from "@/lib/format";
import { CHART_AXIS_COLOR as AXIS, CHART_GRID_COLOR as GRID } from "@/constants/charts";
import type { SegmentRow } from "@/types/api";

const DIMENSION_LABEL: Record<SegmentRow["dimension"], string> = {
  category: "Category", discount_band: "Discount band", price_band: "Price band",
};

// "electronics-and-gadgets" for category, "under-299" / "70%+" for the bands —
// only category uses the merchant-taxonomy label helper, everything else is a slug.
function segmentLabel(dimension: SegmentRow["dimension"], label: string): string {
  return dimension === "category" ? categoryLabel(label) : titleCase(label);
}

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
// "covers 118 of 375 posts (31%)" — the honest-coverage label required next to every
// segment breakdown. Division-by-zero guarded (an empty window has total === 0).
function coverageLabel(categorized: number, total: number): string {
  const pct = total > 0 ? Math.round((categorized / total) * 100) : 0;
  return `covers ${fmtNum(categorized)} of ${fmtNum(total)} posts (${pct}%)`;
}
// "18:00" -> "6 PM", "09:00" -> "9 AM", "00:00" -> "12 AM"
function to12h(hhmm: string): string {
  const h = parseInt(hhmm.slice(0, 2), 10);
  if (Number.isNaN(h)) return hhmm;
  const period = h < 12 ? "AM" : "PM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12} ${period}`;
}

function ChartCard({ title, sub, action, children }: { title: string; sub?: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card className="overflow-hidden">
      <div className="h-1 bg-gradient-to-r from-primary to-primary/30" />
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base font-semibold">{title}</CardTitle>
            {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
          </div>
          {action}
        </div>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

const METRIC_OPTIONS = [
  { value: "engagement_rate", label: "Engagement rate", unit: "%" },
  { value: "total_views", label: "Views", unit: " views" },
  { value: "total_reactions", label: "Reactions", unit: " reactions" },
  { value: "total_forwards", label: "Forwards", unit: " forwards" },
] as const;
type MetricKey = (typeof METRIC_OPTIONS)[number]["value"];

const HOUR_METRIC_OPTIONS = [
  { value: "total_views", label: "Views", unit: " views" },
  { value: "n", label: "Posts", unit: " posts" },
  { value: "total_reactions", label: "Reactions", unit: " reactions" },
  { value: "total_forwards", label: "Forwards", unit: " forwards" },
] as const;
type HourMetricKey = (typeof HOUR_METRIC_OPTIONS)[number]["value"];

function MetricTabs<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: readonly { value: T; label: string; unit: string }[];
}) {
  return (
    <Tabs value={value} onValueChange={(v) => onChange(v as T)}>
      <TabsList>
        {options.map((o) => (
          <TabsTrigger key={o.value} value={o.value} className="text-xs">{o.label}</TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
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
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [segmentMetric, setSegmentMetric] = useState<MetricKey>("engagement_rate");
  const [hourMetric, setHourMetric] = useState<HourMetricKey>("total_views");

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
          Views, reactions, forwards, engagement, and growth — all from the data we collect.
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
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
                <StatCard label="Posts" value={fmtNum(a.total_posts)} sub={`${win.days} days`} />
                <StatCard variant="hero" label="Views" value={fmtNum(a.total_views)} />
                <StatCard label="Total reactions" value={fmtNum(a.total_reactions)} />
                <StatCard label="Total forwards" value={fmtNum(a.total_forwards)}
                  sub="sparsely captured — not a reliable signal" />
                <StatCard label="Eng. rate" value={fmtPct(a.engagement_rate)} sub={`n=${win.n}`} />
              </div>

              <Card className="overflow-hidden">
                <div className="h-1 bg-gradient-to-r from-primary to-primary/30" />
                <CardHeader>
                  <CardTitle className="text-base font-semibold">Segment leaderboard</CardTitle>
                  <p className="text-xs text-muted-foreground">
                    Category / discount band / price band, ranked by engagement rate (reactions + forwards ÷ views).
                    Only segments with at least {a.segments_min_n} posts are ranked, so this is self-auditing —
                    small sample sizes never win.
                  </p>
                </CardHeader>
                <CardContent>
                  {(a.segments ?? []).length ? (
                    <div className="space-y-1.5">
                      {a.segments.map((seg, i) => {
                        const cov = a.dimension_coverage?.[seg.dimension];
                        const covPct = cov && cov.total > 0 ? Math.round((cov.categorized / cov.total) * 100) : 0;
                        return (
                          <div key={`${seg.dimension}:${seg.label}`} className="flex items-center gap-3 rounded-lg bg-primary/10 px-3 py-2">
                            {i === 0 && <span className="text-xs">⭐</span>}
                            <div className="min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{DIMENSION_LABEL[seg.dimension]}</span>
                              </div>
                              <span className="text-sm font-semibold text-foreground">{segmentLabel(seg.dimension, seg.label)}</span>
                            </div>
                            <div className="ml-auto text-right">
                              <p className="text-lg font-bold leading-none text-primary">{fmtPct(seg.engagement_rate)}</p>
                              <p className="mt-1 text-[11px] text-muted-foreground">{seg.n} posts · {covPct}% of posts tagged</p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      Not enough data yet — a segment needs at least {a.segments_min_n} posts to rank.
                    </p>
                  )}
                </CardContent>
              </Card>

              {(() => {
                const segMetric = METRIC_OPTIONS.find((o) => o.value === segmentMetric)!;
                return (
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-medium text-muted-foreground">By category / discount band / price band</p>
                      <MetricTabs value={segmentMetric} onChange={setSegmentMetric} options={METRIC_OPTIONS} />
                    </div>
                    <div className="grid gap-4 lg:grid-cols-3">
                      <ChartCard title={`Category — ${segMetric.label.toLowerCase()}`}
                        sub={`Which categories bring the most ${segMetric.label.toLowerCase()} · hover for post count · ${coverageLabel(a.dimension_coverage?.category?.categorized ?? 0, a.dimension_coverage?.category?.total ?? 0)}`}>
                        <BarsChart data={(a.by_category || []).map((r) => ({ ...r, label: categoryLabel(r.label) }))} unit={segMetric.unit} dataKey={segmentMetric} countKey="n" countLabel="Posts" mutedKey="below_min_n" />
                      </ChartCard>
                      <ChartCard title={`Discount band — ${segMetric.label.toLowerCase()}`}
                        sub={`Does a deeper discount move ${segMetric.label.toLowerCase()} · hover for post count · ${coverageLabel(a.dimension_coverage?.discount_band?.categorized ?? 0, a.dimension_coverage?.discount_band?.total ?? 0)}`}>
                        <BarsChart data={(a.by_discount_band || []).map((r) => ({ ...r, label: titleCase(r.label) }))} unit={segMetric.unit} dataKey={segmentMetric} countKey="n" countLabel="Posts" mutedKey="below_min_n" />
                      </ChartCard>
                      <ChartCard title={`Price band — ${segMetric.label.toLowerCase()}`}
                        sub={`Which price range earns ${segMetric.label.toLowerCase()} · hover for post count · ${coverageLabel(a.dimension_coverage?.price_band?.categorized ?? 0, a.dimension_coverage?.price_band?.total ?? 0)}`}>
                        <BarsChart data={(a.by_price_band || []).map((r) => ({ ...r, label: titleCase(r.label) }))} unit={segMetric.unit} dataKey={segmentMetric} countKey="n" countLabel="Posts" mutedKey="below_min_n" />
                      </ChartCard>
                    </div>
                  </div>
                );
              })()}

              <ChartCard title="Views & engagement over time"
                sub={`Daily total views (area) + engagement rate (dashed) · hover for post count · click a day for detail · ${win.start ? isoSlash(win.start) : "?"} → ${win.end ? isoSlash(win.end) : "?"}`}>
                <TimelineChart data={a.timeline || []} dataKey="total_views" unit=" views"
                  secondaryKey="engagement_rate" secondaryUnit="%" countKey="n" countLabel="Posts"
                  xTickFormatter={isoSlash} onPointClick={setSelectedDay} />
              </ChartCard>

              {selectedDay && (
                <Card className="overflow-hidden">
                  <CardHeader className="flex-row items-center justify-between space-y-0 border-b bg-muted/20">
                    <CardTitle className="text-base">Day detail — {isoSlash(selectedDay)}</CardTitle>
                    <Button variant="ghost" size="sm" onClick={() => setSelectedDay(null)}>
                      <HugeiconsIcon icon={Cancel01Icon} className="h-4 w-4" />
                    </Button>
                  </CardHeader>
                  <CardContent className="pt-4">
                    <DayDetail start={selectedDay} end={selectedDay} />
                  </CardContent>
                </Card>
              )}

              {a.growth?.available && (
                <>
                  <ChartCard title="Subscriber growth" sub="Follower count over time from collection snapshots.">
                    {(() => {
                      const gapDays = Math.max(1, ...a.growth.daily.map((d) => d.spans_days));
                      const gapNote = `${gapDays}-day total`;
                      return (
                        <>
                          {a.growth.has_collection_gap && (
                            <p className="mb-3 rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                              ⚠ Tracking was paused for {gapDays} days in this window. The Joined/Left numbers
                              below are real, but they're the total for all {gapDays} days combined — not one day's activity.
                            </p>
                          )}
                          <div className="grid gap-3 sm:grid-cols-4">
                            <StatCard label="Current subscribers" value={fmtNum(a.growth.current)} />
                            <StatCard label="Joined" value={`+${fmtNum(a.growth.joined)}`}
                              sub={a.growth.has_collection_gap ? gapNote : undefined} />
                            <StatCard label="Left" value={a.growth.left > 0 ? `-${fmtNum(a.growth.left)}` : "0"}
                              sub={a.growth.has_collection_gap ? gapNote : undefined} />
                            <StatCard label="Net change" value={a.growth.net > 0 ? `+${fmtNum(a.growth.net)}` : fmtNum(a.growth.net)}
                              sub={a.growth.has_collection_gap ? gapNote : undefined} />
                          </div>
                        </>
                      );
                    })()}
                    <div className="mt-3">
                      <TimelineChart
                        data={(a.growth.daily || []).map((d) => ({ label: isoSlash(d.date), subs_end: d.subs_end ?? 0 }))}
                        dataKey="subs_end"
                        yDomain={["auto", "auto"]}
                      />
                      {a.growth.daily?.[0]?.is_gap_anchor && (
                        <p className="mt-1.5 text-[11px] leading-snug text-muted-foreground">
                          The first point ({isoSlash(a.growth.daily[0].date)}) is the last known count before the
                          tracking gap — that opening jump is the gap catching up, not a single day's growth.
                        </p>
                      )}
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

              {(() => {
                const hm = HOUR_METRIC_OPTIONS.find((o) => o.value === hourMetric)!;
                return (
                  <div className="grid gap-4 lg:grid-cols-2">
                    <ChartCard title={`Posting activity by hour (IST) — ${hm.label.toLowerCase()}`}
                      sub="All 24 hours — empty slots show 0 · hover for post count"
                      action={<MetricTabs value={hourMetric} onChange={setHourMetric} options={HOUR_METRIC_OPTIONS} />}>
                      <BarsChart data={a.by_hour || []} unit={hm.unit} dataKey={hourMetric} countKey={hourMetric === "n" ? "total_views" : "n"} countLabel={hourMetric === "n" ? "Views" : "Posts"} />
                    </ChartCard>
                    <ChartCard title="Total views by weekday (IST)" sub="Within the selected range · hover for post count">
                      <BarsChart data={a.by_weekday || []} unit=" views" dataKey="total_views" countKey="n" countLabel="Posts" />
                    </ChartCard>
                  </div>
                );
              })()}

              <div className="grid gap-4 lg:grid-cols-3">
                <Card className="flex flex-col overflow-hidden">
                  <div className="h-1 bg-gradient-to-r from-primary to-primary/30" />
                  <CardHeader>
                    <CardTitle className="text-base font-semibold">Best times to post</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3 text-sm flex-1">
                    <p className="text-xs text-muted-foreground">
                      Your strongest posting hours (IST), ranked by typical views per post (a one-off viral
                      post can't skew the ranking). Only hours with at least 3 posts are eligible, so this is
                      self-auditing — small sample sizes never win.
                    </p>
                    {(a.golden_hours ?? []).length ? (
                      <div className="space-y-1.5">
                        {a.golden_hours.map((gh, i) => (
                          <div key={gh.hour} className="flex items-center gap-2 rounded-lg bg-primary/10 px-3 py-2">
                            {i === 0 && <span className="text-xs">⭐</span>}
                            <span className="text-sm font-semibold text-foreground">{to12h(gh.hour)}</span>
                            <span className="text-xs text-muted-foreground">— good to post</span>
                            <span className="ml-auto text-xs text-muted-foreground">
                              ~{fmtNum(gh.median_views)} views typically · {gh.n} posts
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">Not enough data yet — need at least 3 posts in a single hour slot.</p>
                    )}
                  </CardContent>
                </Card>

                <Card className="flex flex-col overflow-hidden">
                  <div className="h-1 bg-gradient-to-r from-primary to-primary/30" />
                  <CardHeader>
                    <CardTitle className="text-base font-semibold">Content signals</CardTitle>
                  </CardHeader>
                  <CardContent className="flex-1 flex flex-col gap-3">
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

                <Card className="flex flex-col overflow-hidden">
                  <div className="h-1 bg-gradient-to-r from-primary to-primary/30" />
                  <CardHeader>
                    <CardTitle className="text-base font-semibold">Subscriber growth</CardTitle>
                  </CardHeader>
                  <CardContent className="flex-1 space-y-3">
                    {a.growth?.available ? (
                      <>
                        {a.growth.has_collection_gap && (
                          <p className="rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                            ⚠ Tracking was paused for {Math.max(1, ...a.growth.daily.map((d) => d.spans_days))} days
                            in this window — the numbers below are real, but cover multiple days combined.
                          </p>
                        )}
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
                          {isoSlash(a.growth.first_date)} → {isoSlash(a.growth.last_date)}
                          {a.growth.has_collection_gap && " (spans a paused-tracking gap)"}
                        </div>
                      </>
                    ) : (
                      <p className="text-sm text-muted-foreground">{a.growth?.reason}</p>
                    )}
                  </CardContent>
                </Card>
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
                {win.n} posts · {win.days} days · {isoSlash(win.start)} → {isoSlash(win.end)}
              </p>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
