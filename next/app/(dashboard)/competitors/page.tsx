"use client";

import { useMemo, useState } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { ChevronDownIcon, Alert01Icon, Idea01Icon } from "@hugeicons/core-free-icons";
import { differenceInCalendarDays } from "date-fns";
import { Async, Empty } from "@/components/Async";
import { CalloutCard } from "@/components/CalloutCard";
import { MultiLineChart, StackedBarsChart } from "@/components/charts";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatCard } from "@/components/StatCard";
import { useCompetitorDashboard, useDataRange, useMerchants } from "@/queries/queries";
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

/** Small proportional inline bar for light visual encoding in table cells. */
function InlineBar({ pct, tone = "default" }: { pct: number; tone?: "default" | "primary" }) {
  const clamped = Number.isFinite(pct) ? Math.min(100, Math.max(0, pct)) : 0;
  return (
    <div className="h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-muted">
      <div
        className={cn("h-full rounded-full", tone === "primary" ? "bg-primary" : "bg-muted-foreground/40")}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}

function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${Math.round(n * 100)}%`;
}

const STYLE_DIMS: { key: string; label: string; fmt?: (v: any) => string }[] = [
  { key: "avg_views_per_post", label: "Avg views", fmt: (v: any) => fmtNum(v) },
  { key: "posts_per_day", label: "Posts/day", fmt: (v: any) => Number(v).toFixed(2) },
  { key: "cta_rate", label: "CTA rate", fmt: (v: any) => fmtPct(v) },
  { key: "coupon_rate", label: "Coupon rate", fmt: (v: any) => fmtPct(v) },
  { key: "multi_deal_rate", label: "Multi-deal", fmt: (v: any) => fmtPct(v) },
  { key: "media_rate", label: "Media rate", fmt: (v: any) => fmtPct(v) },
  { key: "emoji_rate", label: "Emoji/post", fmt: (v: any) => Number(v).toFixed(1) },
  { key: "avg_text_len", label: "Caption len", fmt: (v: any) => Number(v).toFixed(0) },
  { key: "hashtag_rate", label: "Hashtags/post", fmt: (v: any) => Number(v).toFixed(2) },
  { key: "avg_links", label: "Links/post", fmt: (v: any) => Number(v).toFixed(2) },
];

function CompCard({ e, isBest }: { e: CompetitorEntity; isBest: Record<string, boolean> }) {
  const [open, setOpen] = useState(false);
  const catBadge = e.category === "platform"
    ? <Badge variant="primary">Platform + Telegram</Badge>
    : e.category === "channel"
      ? <Badge variant="outline">Telegram only</Badge>
      : <Badge variant="outline">Unclassified</Badge>;

  const topDims = STYLE_DIMS.slice(0, 3);
  const restDims = STYLE_DIMS.slice(3);

  return (
    <Card className="transition-all duration-200">
      <div className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              {catBadge}
              <span className="font-semibold truncate">{e.name}</span>
              {e.similarity_to_us != null && !e.is_owned && (
                <span className="text-xs text-muted-foreground">
                  {(e.similarity_to_us * 100).toFixed(0)}% similar
                </span>
              )}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {topDims.map((dim) => {
                const v = e[dim.key];
                if (v == null) return null;
                return (
                  <span key={dim.key}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
                      isBest[dim.key] ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
                    )}
                  >
                    <span className="text-muted-foreground">{dim.label}</span>
                    {dim.fmt ? dim.fmt(v) : v}
                  </span>
                );
              })}
            </div>
          </div>
          <span className="shrink-0 text-xs text-muted-foreground">{e.posts ?? "?"} posts</span>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          {(e.benchmarks ?? []).slice(0, 3).map((b) => (
            <span key={b.dimension}
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs",
                b.delta != null && b.delta > 0
                  ? "bg-emerald-50 text-emerald-700"
                  : "bg-muted text-muted-foreground",
              )}
            >
              {b.dimension}: {b.delta != null ? `${b.delta >= 0 ? "+" : ""}${(b.owned_value ? (b.delta / b.owned_value * 100).toFixed(0) : "—")}%` : "—"}
            </span>
          ))}
          {e.tenure_label && (
            <span className="text-xs text-muted-foreground">{e.tenure_label}</span>
          )}
        </div>

        {open && (
          <div className="mt-3 space-y-3 border-t pt-3">
            <div className="flex flex-wrap gap-1.5">
              {restDims.map((dim) => {
                const v = e[dim.key];
                if (v == null) return null;
                return (
                  <Badge key={dim.key} variant={isBest[dim.key] ? "primary" : "outline"} className="text-xs">
                    {dim.label}: {dim.fmt ? dim.fmt(v) : v}
                  </Badge>
                );
              })}
            </div>

            {(e.benchmarks ?? []).length > 3 && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">More benchmarks</p>
                <div className="flex flex-wrap gap-1.5">
                  {(e.benchmarks ?? []).slice(3).map((b) => (
                    <Badge key={b.dimension}
                      variant={b.delta != null && b.delta > 0 ? "warning" : "default"}
                      className="text-xs">
              {b.dimension}: {b.delta != null ? `${b.delta >= 0 ? "+" : ""}${(b.owned_value ? (b.delta / b.owned_value * 100).toFixed(0) : "—")}%` : "—"}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {e.deal_mix && Object.keys(e.deal_mix).length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">Deal mix</p>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(e.deal_mix).map(([t, s]: [string, any]) => (
                    <Badge key={t} variant="outline" className="text-xs">
                      {t}: {(s * 100).toFixed(0)}%
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="mt-2 flex w-full items-center justify-center gap-1 rounded-md py-1 text-xs text-muted-foreground hover:bg-muted/50 hover:text-foreground transition-colors"
        >
          <HugeiconsIcon icon={ChevronDownIcon} className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
          {open ? "Less" : `${restDims.filter((d) => e[d.key] != null).length} more metrics`}
        </button>
      </div>
    </Card>
  );
}

function MerchantsTab() {
  const q = useMerchants();
  return (
    <Async q={q} rows={2}>
      {(d) => {
        const coverage = d.coverage?.owned;
        const channels = [...(d.mix?.channels || [])].sort((a, b) => (b.is_owned ? 1 : 0) - (a.is_owned ? 1 : 0));
        const merchants = d.mix?.merchants || [];
        const maxViewsPerDay = Math.max(
          0,
          ...(d.profiles || []).map((p) => p.avg_views_per_day ?? 0),
        );

        return (
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Your channel · merchant performance</CardTitle>
                {coverage && (
                  <p className="text-xs text-muted-foreground">
                    Merchant resolved on {fmtNum(coverage.resolved)} of {fmtNum(coverage.total)} posts
                    ({Math.round(coverage.pct * 100)}%). Only posts with a recognized store link are counted —
                    shortlinks stay unresolved.
                  </p>
                )}
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Merchant</TableHead>
                      <TableHead>Posts</TableHead>
                      <TableHead>Views/day</TableHead>
                      <TableHead>Median price</TableHead>
                      <TableHead>Sample</TableHead>
                      <TableHead>Confidence</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(d.profiles || []).map((p) => {
                      const lowConfidence = p.confidence < 0.3 || p.posts < 10;
                      return (
                        <TableRow key={p.merchant} className={cn(lowConfidence && "text-muted-foreground")}>
                          <TableCell className="font-medium">
                            <div className="flex items-center gap-2">
                              <span>{p.merchant}</span>
                              {lowConfidence && (
                                <Badge variant="outline" className="text-[10px] font-normal text-muted-foreground">
                                  low sample
                                </Badge>
                              )}
                            </div>
                          </TableCell>
                          <TableCell>{p.posts}</TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <span>{p.avg_views_per_day != null ? Math.round(p.avg_views_per_day) : "—"}</span>
                              {p.avg_views_per_day != null && maxViewsPerDay > 0 && (
                                <InlineBar pct={(p.avg_views_per_day / maxViewsPerDay) * 100} />
                              )}
                            </div>
                          </TableCell>
                          <TableCell>{p.price_median != null ? `₹${fmtNum(p.price_median)}` : "—"}</TableCell>
                          <TableCell>{fmtNum(p.price_sample_size)}</TableCell>
                          <TableCell>
                            <Badge variant={lowConfidence ? "outline" : "secondary"} className="text-xs">
                              {fmtPct(p.confidence)}
                            </Badge>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                    {(d.profiles || []).length === 0 && (
                      <TableRow>
                        <TableCell colSpan={6} className="text-center text-sm text-muted-foreground">
                          No merchant data yet.
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Merchant mix — you vs competitors</CardTitle>
                <p className="text-xs text-muted-foreground">
                  Share of resolved posts per merchant, compared across channels.
                </p>
              </CardHeader>
              <CardContent className="p-0">
                {channels.length < 2 ? (
                  <p className="p-4 text-sm text-muted-foreground">
                    Not enough resolved merchant data across channels to compare yet.
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Merchant</TableHead>
                          {channels.map((c) => (
                            <TableHead key={c.name} className={cn(c.is_owned && "text-primary")}>
                              <div>{c.is_owned ? "You" : c.name}</div>
                              {c.coverage_pct != null && (
                                <div className="text-[10px] font-normal text-muted-foreground">
                                  {fmtPct(c.coverage_pct)} resolved
                                </div>
                              )}
                            </TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {merchants.map((m) => (
                          <TableRow key={m}>
                            <TableCell className="font-medium">{m}</TableCell>
                            {channels.map((c) => {
                              const share = c.shares?.[m];
                              return (
                                <TableCell key={c.name} className={cn(c.is_owned && "font-medium text-primary")}>
                                  <div className="flex items-center gap-2">
                                    <span>{fmtPct(share)}</span>
                                    {share != null && (
                                      <InlineBar pct={share * 100} tone={c.is_owned ? "primary" : "default"} />
                                    )}
                                  </div>
                                </TableCell>
                              );
                            })}
                          </TableRow>
                        ))}
                        {merchants.length === 0 && (
                          <TableRow>
                            <TableCell colSpan={channels.length + 1} className="text-center text-sm text-muted-foreground">
                              No merchant mix data yet.
                            </TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>

            <section>
              <h2 className="mb-3 text-lg font-semibold">Opportunities</h2>
              <div className="space-y-3">
                {(d.opportunities || []).map((o, i) => (
                  <CalloutCard
                    key={i}
                    severity="info"
                    label={o.kind}
                    title={o.description}
                  >
                    {o.merchant && <Badge variant="primary">{o.merchant}</Badge>}
                  </CalloutCard>
                ))}
                {(d.opportunities || []).length === 0 && (
                  <p className="text-sm text-muted-foreground">No merchant opportunities surfaced.</p>
                )}
              </div>
            </section>
          </div>
        );
      }}
    </Async>
  );
}

function SignalsSection({ signals }: { signals: any[] }) {
  if (!signals.length) return null;
  const threats = signals.filter((s) => s.type === "threat");
  const opportunities = signals.filter((s) => s.type === "opportunity");
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold">Signals &amp; opportunities</h2>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <HugeiconsIcon icon={Alert01Icon} className="h-4 w-4 text-orange-500" />
              <CardTitle className="text-sm font-semibold">Threats</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {threats.length === 0 ? (
              <p className="text-sm text-muted-foreground">No threats detected.</p>
            ) : (
              threats.map((s, i) => (
                <CalloutCard key={i} severity="warning" label={s.competitor} title={s.description}>
                  {s.kind}
                </CalloutCard>
              ))
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <HugeiconsIcon icon={Idea01Icon} className="h-4 w-4 text-emerald-500" />
              <CardTitle className="text-sm font-semibold">Opportunities</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {opportunities.length === 0 ? (
              <p className="text-sm text-muted-foreground">No opportunities spotted.</p>
            ) : (
              opportunities.map((s, i) => (
                <CalloutCard key={i} severity="success" label={s.competitor} title={s.description}>
                  {s.kind}
                </CalloutCard>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </section>
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
  const tab = get("tab", "all") as "all" | "platform" | "channel" | "merchants";

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
          Date range applies to competitor metrics only — the Merchants tab always shows all-time data.
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
            <TabsTrigger value="merchants">Merchants</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {tab === "merchants" ? <MerchantsTab /> : (
        <Async q={q} rows={2}>
          {(d) => {
            if ((d.platform ?? []).length === 0 && (d.channel ?? []).length === 0) {
              return <Empty>No competitor data yet. Run competitor discovery first.</Empty>;
            }

            const rawEntities = [...(d.platform ?? []), ...(d.channel ?? [])];
            const entities = tab === "all" ? rawEntities : rawEntities.filter((e: any) => e.category === tab);

            const best: Record<string, boolean> = {};
            STYLE_DIMS.forEach((dim) => {
              const vals = entities.map((e: any) => e[dim.key]).filter((v: any) => v != null);
              const maxV = vals.length ? Math.max(...vals) : null;
              entities.forEach((e: any) => {
                if (e[dim.key] != null && maxV != null && e[dim.key] === maxV) best[`${e.name}_${dim.key}`] = true;
              });
            });

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
                <div className="grid gap-6 sm:grid-cols-4">
                  <StatCard label="Competitors" value={fmtNum(d.summary?.total ?? 0)} />
                  <StatCard label="Direct (platform)" value={fmtNum(d.summary?.platform ?? 0)} />
                  <StatCard label="Indirect (Telegram)" value={fmtNum(d.summary?.channel ?? 0)} />
                  <StatCard label="Signals" value={fmtNum(d.summary?.signals ?? 0)} />
                </div>

                <div className="space-y-2">
                  <h2 className="text-lg font-semibold">
                    {tab === "all" ? "All competitors" : tab === "platform" ? "Direct competitors" : "Indirect competitors"}
                    <span className="ml-2 text-sm font-normal text-muted-foreground">{entities.length}</span>
                  </h2>
                  {entities.length === 0 ? (
                    <Empty>No competitors in this category.</Empty>
                  ) : (
                    entities.map((e: any) => (
                      <CompCard key={e.name} e={e}
                        isBest={Object.fromEntries(STYLE_DIMS.map((dim) => [dim.key, best[`${e.name}_${dim.key}`]]))} />
                    ))
                  )}
                </div>

                {entities.length >= 2 && (
                  <Card>
                    <CardHeader><CardTitle className="text-base">Style &amp; behaviour benchmark</CardTitle>
                      </CardHeader>
                    <CardContent className="overflow-x-auto p-0">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Metric</TableHead>
                            {entities.map((e: any, i: number) => (
                              <TableHead key={i} className="text-right">{e.name}</TableHead>
                            ))}
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {STYLE_DIMS.map((dim) => {
                            const vals = entities.map((e: any) => e[dim.key]);
                            const numeric = vals.filter((v: any) => v != null && typeof v === "number");
                            const bestV = numeric.length ? Math.max(...numeric) : null;
                            return (
                              <TableRow key={dim.key} className="hover:bg-muted/50">
                                <TableCell className="text-xs text-muted-foreground">{dim.label}</TableCell>
                                {entities.map((e: any, i: number) => {
                                  const v = e[dim.key];
                                  const isB = v != null && bestV != null && v === bestV;
                                  return (
                                    <TableCell key={i} className={cn("text-right font-mono text-xs", isB && "font-bold text-green-500")}>
                                      {v != null ? (dim.fmt ? dim.fmt(v) : v) : "—"}
                                    </TableCell>
                                  );
                                })}
                              </TableRow>
                            );
                          })}
                        </TableBody>
                      </Table>
                    </CardContent>
                  </Card>
                )}

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

                <SignalsSection signals={d.signals ?? []} />
              </div>
            );
          }}
        </Async>
      )}
    </div>
  );
}
