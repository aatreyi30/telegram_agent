"use client";

import { useMemo } from "react";
import { Async, Empty } from "@/components/Async";
import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { BarsChart } from "@/components/charts";
import { useDataRange, useDay } from "@/queries/queries";
import { DateFilter } from "@/components/ui/date-range-picker";
import { useQueryParams } from "@/lib/use-search-params";

function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}

function fmtPct(n: number | null | undefined, signed = false): string {
  if (n === null || n === undefined) return "—";
  const s = signed && n > 0 ? "+" : "";
  return `${s}${Math.round(n)}%`;
}

export default function DayViewPage() {
  const range = useDataRange();
  const min = range.data?.min ?? undefined;
  const max = range.data?.max ?? undefined;

  const { get, set } = useQueryParams();
  const date = get("date", "");

  const q = useDay(date || null, { enabled: !!range.data });

  const resolvedDate = (() => {
    if (date) return date;
    if (q.data && "date" in q.data && q.data.date) return q.data.date;
    return max || "";
  })();

  const handleDateChange = (val: string) => {
    set({ date: val || null });
  };

  const typeMixChart = useMemo(() => {
    if (!q.data || !("type_mix" in q.data)) return null;
    return (q.data.type_mix || []).map(([label, count]: [string, number]) => ({ label, count }));
  }, [q.data]);

  const merchantMixChart = useMemo(() => {
    if (!q.data || !("merchant_mix" in q.data)) return null;
    return (q.data.merchant_mix || []).map(([label, count]: [string, number]) => ({ label, count }));
  }, [q.data]);

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-2xl font-bold tracking-tight">Day view</h1>
        <p className="text-sm text-muted-foreground">Per-merchant breakdown for a specific date (IST).</p>
      </div>

      <div className="mb-2 flex flex-wrap items-end gap-2">
        <DateFilter
          mode="single"
          value={resolvedDate}
          onChange={handleDateChange}
          min={min}
          max={max}
          showArrows
        />
      </div>

      {max && <p className="mb-4 text-xs text-muted-foreground">Collected data runs {min} → {max} (IST).</p>}

      <Async q={q} rows={2}>
        {(d) =>
          !d.available ? (
            <Empty>{d.note || "No posts on this date."}</Empty>
          ) : (
            <div className="space-y-4">
              <div className="grid gap-6 sm:grid-cols-4">
                <StatCard label="posts" value={fmtNum(d.posts)} />
                <StatCard label="total views" value={fmtNum(d.total_views)} />
                <StatCard
                  label="avg views/post"
                  value={fmtNum(d.avg_views_per_post)}
                  sub={d.vs_baseline?.views_delta_pct != null ? `${fmtPct(d.vs_baseline.views_delta_pct, true)} vs 30d` : undefined}
                />
                <StatCard label="active merchants" value={String((d.merchants ?? []).filter((m) => m.key).length ?? 0)} sub={d.merchantless_count > 0 ? `${d.merchantless_count} without merchant` : undefined} />
              </div>

              <Card>
                <CardHeader>
                  <div className="h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50 mb-2" />
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base">Merchants — {d.date}</CardTitle>
                    {d.baseline && (
                      <span className="text-xs text-muted-foreground">
                        vs 30d: {fmtPct(d.vs_baseline?.views_delta_pct, true)} views · {d.vs_baseline?.posts_delta != null ? (d.vs_baseline.posts_delta >= 0 ? "+" : "") + d.vs_baseline.posts_delta : "—"} posts
                      </span>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="p-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Merchant</TableHead>
                        <TableHead className="text-right">Posts</TableHead>
                        <TableHead className="text-right">Views</TableHead>
                        <TableHead className="text-right">Reactions</TableHead>
                        <TableHead className="text-right">Fwds</TableHead>
                        <TableHead className="text-right">Eng.&nbsp;rate</TableHead>
                        <TableHead className="text-right">Deals</TableHead>
                        <TableHead>Types</TableHead>
                        <TableHead>Top post <span className="text-xs font-normal text-muted-foreground">(views)</span></TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {d.merchants.map((m, idx) => (
                        <TableRow key={m.key ?? `__unknown__${idx}`} className="hover:bg-muted/50">
                          <TableCell className="font-medium">{m.display_name ?? m.key}</TableCell>
                          <TableCell className="text-right">{fmtNum(m.post_count)}</TableCell>
                          <TableCell className="text-right font-semibold">{fmtNum(m.total_views)}</TableCell>
                          <TableCell className="text-right">{m.total_reactions ? fmtNum(m.total_reactions) : "—"}</TableCell>
                          <TableCell className="text-right">{m.total_forwards ? fmtNum(m.total_forwards) : "—"}</TableCell>
                          <TableCell className="text-right">{m.engagement_rate != null ? `${m.engagement_rate}%` : "—"}</TableCell>
                          <TableCell className="text-right">{m.deal_count ? fmtNum(m.deal_count) : "—"}</TableCell>
                          <TableCell className="max-w-40 text-xs text-muted-foreground">
                            {Object.entries(m.type_dist ?? {}).length
                              ? Object.entries(m.type_dist ?? {}).map(([t, c]) => `${t}(${c})`).join(", ")
                              : "—"}
                          </TableCell>
                          <TableCell className="max-w-48 truncate text-muted-foreground">
                            {m.top_post ? (
                              <span title={`views: ${m.top_post.views} — ${m.top_post.preview}`}>
                                <span className="font-semibold text-foreground">{fmtNum(m.top_post.views)}</span>
                                {" "}{m.top_post.preview}
                              </span>
                            ) : "—"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>

              <div className="grid gap-4 md:grid-cols-2">
                <Card>
                  <CardHeader>
                    <div className="h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50 mb-2" />
                    <CardTitle className="text-base">Post-type mix</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {typeMixChart ? (
                      <BarsChart data={typeMixChart} dataKey="count" unit=" posts" height={200} />
                    ) : (
                      <div className="space-y-1 text-sm">
                        {d.type_mix.map((t) => (
                          <div key={t[0]} className="flex items-center justify-between">
                            <span>{t[0]}</span>
                            <Badge>{t[1]}</Badge>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <div className="h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50 mb-2" />
                    <CardTitle className="text-base">Merchant concentration</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {merchantMixChart ? (
                      <BarsChart data={merchantMixChart} dataKey="count" unit=" posts" height={200} />
                    ) : (
                      <p className="text-sm text-muted-foreground">No merchant data.</p>
                    )}
                  </CardContent>
                </Card>
              </div>

              <div className="grid gap-4 sm:grid-cols-4 items-stretch">
                <Card>
                  <CardHeader>
                    <div className="h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50 mb-2" />
                    <CardTitle className="text-base">Engagement</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">Reactions</span>
                      <span className="font-semibold">{fmtNum(d.merchants.reduce((a, m) => a + (m.total_reactions || 0), 0))}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">Forwards</span>
                      <span className="font-semibold">{fmtNum(d.merchants.reduce((a, m) => a + (m.total_forwards || 0), 0))}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">Avg rate</span>
                      <span className="font-semibold">
                        {(() => {
                          const rates = d.merchants.map((m) => m.engagement_rate).filter((r): r is number => r != null);
                          return rates.length ? `${(rates.reduce((a, b) => a + b, 0) / rates.length).toFixed(1)}%` : "—";
                        })()}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">Total eng.</span>
                      <span className="font-semibold">{fmtNum(d.merchants.reduce((a, m) => a + (m.total_engagement || 0), 0))}</span>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <div className="h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50 mb-2" />
                    <CardTitle className="text-base">Deals</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">Deal posts</span>
                      <span className="font-semibold">{fmtNum(d.merchants.reduce((a, m) => a + (m.deal_count || 0), 0))}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">% of posts</span>
                      <span className="font-semibold">{d.posts ? `${Math.round(d.merchants.reduce((a, m) => a + (m.deal_count || 0), 0) / d.posts * 100)}%` : "—"}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">Top merchant</span>
                      <span className="font-semibold truncate max-w-32" title={(() => { const t = d.merchants.filter((m) => m.key)[0]; return t?.display_name ?? t?.key; })()}>
                        {(() => { const t = d.merchants.filter((m) => m.key)[0]; return t?.display_name ?? t?.key ?? "—"; })()}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">Active merchants</span>
                      <span className="font-semibold">{d.merchants.filter((m) => m.key && m.deal_count > 0).length}</span>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <div className="h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50 mb-2" />
                    <CardTitle className="text-base">Post types</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1 text-sm">
                    {d.type_mix.map((t) => (
                      <div key={t[0]} className="flex items-center justify-between">
                        <span className="text-muted-foreground">{t[0]}</span>
                        <span className="font-semibold">{t[1]}</span>
                      </div>
                    ))}
                    {d.type_mix.length === 0 && <p className="text-sm text-muted-foreground">—</p>}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <div className="h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50 mb-2" />
                    <CardTitle className="text-base">vs 30-day avg</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground text-sm">Posts/day</span>
                      <span className="font-semibold">{d.baseline.avg_posts_per_day.toFixed(1)} vs {d.posts}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground text-sm">Avg views</span>
                      <span className="font-semibold">{fmtNum(d.baseline.avg_views_per_post)} vs {fmtNum(d.avg_views_per_post)}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground text-sm">Views Δ</span>
                      <span className={d.vs_baseline?.views_delta_pct != null && d.vs_baseline.views_delta_pct >= 0 ? "font-semibold text-green-600" : "font-semibold text-red-600"}>
                        {d.vs_baseline?.views_delta_pct != null ? fmtPct(d.vs_baseline.views_delta_pct, true) : "—"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground text-sm">Posts Δ</span>
                      <span className="font-semibold">
                        {d.vs_baseline?.posts_delta != null ? (d.vs_baseline.posts_delta >= 0 ? "+" : "") + d.vs_baseline.posts_delta : "—"}
                      </span>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>
          )
        }
      </Async>
    </div>
  );
}
