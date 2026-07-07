"use client";

import { useState } from "react";
import { ChevronDown, TrendingUp, TrendingDown, AlertTriangle, Lightbulb } from "lucide-react";
import { Async, Empty } from "@/components/Async";
import { CalloutCard } from "@/components/CalloutCard";
import { MultiLineChart, StackedBarsChart } from "@/components/charts";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatCard } from "@/components/StatCard";
import { useCompetitorDashboard, useMerchants } from "@/queries/queries";
import type { CompetitorEntity } from "@/types/api";
import { cn } from "@/lib/utils";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DateFilter } from "@/components/ui/date-range-picker";
import { useQueryParams } from "@/lib/use-search-params";

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
              {b.dimension}: {b.delta != null ? `${b.delta >= 0 ? "+" : ""}${(b.delta * 100).toFixed(0)}%` : "—"}
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
                      {b.dimension}: {b.delta != null ? `${b.delta >= 0 ? "+" : ""}${(b.delta * 100).toFixed(0)}%` : "—"}
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
          <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
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
              <AlertTriangle className="h-4 w-4 text-orange-500" />
              <CardTitle className="text-sm font-semibold">Threats</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {threats.length === 0 ? (
              <p className="text-sm text-muted-foreground">No threats detected.</p>
            ) : (
              threats.map((s, i) => (
                <div key={i} className="flex items-start gap-3 rounded-lg border border-orange-200 bg-orange-50/50 p-3">
                  <TrendingDown className="mt-0.5 h-4 w-4 shrink-0 text-orange-500" />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-xs">{s.competitor}</Badge>
                      <span className="text-xs text-muted-foreground">{s.kind}</span>
                    </div>
                    <p className="mt-1 text-sm">{s.description}</p>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Lightbulb className="h-4 w-4 text-emerald-500" />
              <CardTitle className="text-sm font-semibold">Opportunities</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {opportunities.length === 0 ? (
              <p className="text-sm text-muted-foreground">No opportunities spotted.</p>
            ) : (
              opportunities.map((s, i) => (
                <div key={i} className="flex items-start gap-3 rounded-lg border border-emerald-200 bg-emerald-50/50 p-3">
                  <TrendingUp className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-xs">{s.competitor}</Badge>
                      <span className="text-xs text-muted-foreground">{s.kind}</span>
                    </div>
                    <p className="mt-1 text-sm">{s.description}</p>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </section>
  );
}

export default function CompetitorDashboardPage() {
  const { get, set } = useQueryParams();
  const winParam = get("window", "");
  const window = winParam ? Number(winParam) : undefined;

  const [tab, setTab] = useState<"all" | "platform" | "channel" | "merchants">("all");

  const q = useCompetitorDashboard(window);

  const handlePreset = (preset: string) => {
    if (preset === "all") set({ window: "" });
    else set({ window: preset.replace("d", "") });
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
          preset={window ? `${window}d` : "all"}
          onPresetChange={handlePreset}
          from={undefined}
          to={undefined}
          onRangeChange={() => {}}
          showArrows={false}
          presetsOnly
        />
        <Tabs value={tab} onValueChange={(v) => setTab(v as "all" | "platform" | "channel" | "merchants")} className="ml-auto">
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

                {d.unavailable?.length > 0 && (
                  <div className="rounded-lg border bg-muted/40 p-3 text-xs text-muted-foreground">
                    <b>Unavailable:</b> {d.unavailable.join(", ")}. {d.note}
                  </div>
                )}

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
