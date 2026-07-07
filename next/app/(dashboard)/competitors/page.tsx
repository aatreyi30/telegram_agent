"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { Async, Empty } from "@/components/Async";
import { CalloutCard } from "@/components/CalloutCard";
import { MultiLineChart, StackedBarsChart } from "@/components/charts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatCard } from "@/components/StatCard";
import { useCompetitorDashboard, useMerchants } from "@/queries/queries";
import type { CompetitorEntity } from "@/types/api";
import { cn } from "@/lib/utils";

// `fe/`'s lib/utils has fmtNum/fmtPct helpers; next/ doesn't (yet), so they're
// reproduced locally. fmtPct here takes a 0-1 fraction (matching the backend's
// `*_rate` fields, which are all fractions) and multiplies by 100 before
// rounding — `fe/`'s fmtPct rounds the raw fraction without scaling, which
// under-displays these values; this port fixes that rather than copying the bug.
function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}

function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${Math.round(n * 100)}%`;
}

const PERIODS: { label: string; value: number | undefined }[] = [
  { label: "7d", value: 7 },
  { label: "30d", value: 30 },
  { label: "90d", value: 90 },
  { label: "All", value: undefined },
];

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

  return (
    <Card className="hover-lift">
      <CardHeader className="cursor-pointer select-none py-3" onClick={() => setOpen((o) => !o)}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")} />
            <span className="font-semibold">{e.name}</span>
            {catBadge}
            {e.similarity_to_us != null && !e.is_owned && (
              <span className="text-xs text-muted-foreground">
                {(e.similarity_to_us * 100).toFixed(0)}% similar
              </span>
            )}
          </div>
          <span className="text-xs text-muted-foreground">{e.posts ?? "?"} posts</span>
        </div>
      </CardHeader>
      <CardContent className={open ? "space-y-3 pb-4" : "hidden"}>
        {/* Metric chips */}
        <div className="flex flex-wrap gap-2">
          {STYLE_DIMS.map((dim) => {
            const v = e[dim.key];
            if (v == null) return null;
            return (
              <Badge key={dim.key} variant={isBest[dim.key] ? "primary" : "outline"} className="text-xs">
                {dim.label}: {dim.fmt ? dim.fmt(v) : v}
              </Badge>
            );
          })}
        </div>

        {/* Benchmarks */}
        {(e.benchmarks ?? []).length > 0 && (
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">Benchmark vs you</p>
            <div className="flex flex-wrap gap-1.5">
              {(e.benchmarks ?? []).slice(0, 6).map((b) => (
                <Badge key={b.dimension}
                  variant={b.delta != null && b.delta > 0 ? "warning" : "default"}
                  className="text-xs">
                  {b.dimension}: {b.delta != null ? `${b.delta >= 0 ? "+" : ""}${(b.delta * 100).toFixed(0)}%` : "—"}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Deal mix */}
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

        {/* Tenure */}
        {e.tenure_label && (
          <p className="text-xs text-muted-foreground">{e.tenure_label}</p>
        )}
      </CardContent>
    </Card>
  );
}

function MerchantsTab() {
  const q = useMerchants();
  return (
    <Async q={q} rows={2}>
      {(d) => (
        <div className="space-y-6">
          <Card>
            <CardHeader><CardTitle className="text-base">Profiles</CardTitle></CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Merchant</TableHead>
                    <TableHead>Posts</TableHead>
                    <TableHead>Views/day</TableHead>
                    <TableHead>Median price</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(d.profiles || []).map((p) => (
                    <TableRow key={p.merchant}>
                      <TableCell className="font-medium">{p.merchant}</TableCell>
                      <TableCell>{p.posts}</TableCell>
                      <TableCell>{p.avg_views_per_day != null ? Math.round(p.avg_views_per_day) : "—"}</TableCell>
                      <TableCell>{p.price_median != null ? `₹${fmtNum(p.price_median)}` : "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
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
      )}
    </Async>
  );
}

export default function CompetitorDashboardPage() {
  const [window, setWindow] = useState<number | undefined>(undefined);
  const [tab, setTab] = useState<"all" | "platform" | "channel" | "merchants">("all");

  const q = useCompetitorDashboard(window);

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-2xl font-bold tracking-tight">Competitor dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Direct competitors (platform + Telegram) vs Telegram-only channels — all metrics, side by side.
        </p>
      </div>

      {/* Period + category filter */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex gap-1.5">
          {PERIODS.map((p) => (
            <Button key={p.label} size="sm" variant={window === p.value ? "default" : "outline"}
              onClick={() => setWindow(p.value)}>
              {p.label}
            </Button>
          ))}
        </div>
        <div className="ml-auto flex gap-1.5">
          {(["all", "platform", "channel", "merchants"] as const).map((t) => (
            <Button key={t} size="sm" variant={tab === t ? "default" : "outline"}
              onClick={() => setTab(t)}>
              {t === "merchants" ? "Merchants" : t === "all" ? "All" : t === "platform" ? "Direct" : "Indirect"}
            </Button>
          ))}
        </div>
      </div>

      {tab === "merchants" ? <MerchantsTab /> : (
        <Async q={q} rows={2}>
          {(d) => {
            if ((d.platform ?? []).length === 0 && (d.channel ?? []).length === 0) {
              return <Empty>No competitor data yet. Run competitor discovery first.</Empty>;
            }

            const rawEntities = [...(d.platform ?? []), ...(d.channel ?? [])];
            const entities = tab === "all" ? rawEntities : rawEntities.filter((e: any) => e.category === tab);

            // Best in class for each dimension
            const best: Record<string, boolean> = {};
            STYLE_DIMS.forEach((dim) => {
              const vals = entities.map((e: any) => e[dim.key]).filter((v: any) => v != null);
              const maxV = vals.length ? Math.max(...vals) : null;
              entities.forEach((e: any) => {
                if (e[dim.key] != null && maxV != null && e[dim.key] === maxV) best[`${e.name}_${dim.key}`] = true;
              });
            });

            // Deal types across entities for chart
            const allTypes = new Set<string>();
            entities.forEach((e: any) => { if (e.deal_mix) Object.keys(e.deal_mix).forEach((t) => allTypes.add(t)); });
            const dealTypes = Array.from(allTypes);

            // Weekday + hourly for MultiLineChart
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

            // Deal mix for StackedBarsChart
            const dealData = entities.map((e: any) => {
              const row: any = { label: e.name };
              dealTypes.forEach((t) => { row[t] = e.deal_mix?.[t] ?? 0; });
              return row;
            });
            const dealKeys = dealTypes.map((t) => ({ key: t, name: t }));

            return (
              <div className="space-y-4">
                {/* Summary */}
                <div className="grid gap-4 sm:grid-cols-4">
                  <StatCard label="Competitors" value={fmtNum(d.summary?.total ?? 0)} />
                  <StatCard label="Direct (platform)" value={fmtNum(d.summary?.platform ?? 0)} />
                  <StatCard label="Indirect (Telegram)" value={fmtNum(d.summary?.channel ?? 0)} />
                  <StatCard label="Signals" value={fmtNum(d.summary?.signals ?? 0)} />
                </div>

                {d.unavailable?.length > 0 && (
                  <div className="rounded-lg border bg-muted/40 p-3 text-xs text-muted-foreground">
                    <b>Unavailable:</b> {d.unavailable.join(", ")}. {d.note}
                  </div>
                )}

                {/* Per-competitor cards */}
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

                {/* Comparison benchmark table */}
                {entities.length >= 2 && (
                  <Card>
                    <CardHeader><CardTitle className="text-base">Style &amp; behaviour benchmark</CardTitle>
                      <p className="text-xs text-muted-foreground">Side-by-side. <span className="text-green-500">Green</span> = best in row.</p></CardHeader>
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
                              <TableRow key={dim.key}>
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

                {/* Deal mix chart */}
                {dealTypes.length > 0 && entities.length >= 2 && (
                  <Card>
                    <CardHeader><CardTitle className="text-base">Deal-type mix</CardTitle>
                      <p className="text-xs text-muted-foreground">What each competitor emphasises.</p></CardHeader>
                    <CardContent>
                      <StackedBarsChart data={dealData} keys={dealKeys} unit="%" height={260} />
                    </CardContent>
                  </Card>
                )}

                {/* Weekday + Hourly */}
                {entities.length >= 2 && (
                  <div className="grid gap-4 lg:grid-cols-2">
                    <Card>
                      <CardHeader><CardTitle className="text-base">Posting by weekday</CardTitle></CardHeader>
                      <CardContent>
                        <MultiLineChart data={wdData} series={weekSeries} unit=" posts" height={220} />
                      </CardContent>
                    </Card>
                    <Card>
                      <CardHeader><CardTitle className="text-base">Posting by hour (IST)</CardTitle></CardHeader>
                      <CardContent>
                        <MultiLineChart data={hourly} series={hourSeries} unit=" posts" height={220} />
                      </CardContent>
                    </Card>
                  </div>
                )}

                {/* Signals */}
                {(d.signals ?? []).length > 0 && (
                  <section>
                    <h2 className="mb-3 text-lg font-semibold">Signals &amp; opportunities</h2>
                    <div className="space-y-3">
                      {(d.signals ?? []).map((s: any, i: number) => (
                        <CalloutCard
                          key={i}
                          severity={s.type === "threat" ? "warning" : "info"}
                          label={s.competitor}
                          title={s.description}
                        >
                          {s.kind}
                        </CalloutCard>
                      ))}
                    </div>
                  </section>
                )}
              </div>
            );
          }}
        </Async>
      )}
    </div>
  );
}
