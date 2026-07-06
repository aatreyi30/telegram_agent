import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Async, Empty } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { Badge } from "@/components/ui/primitives";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/services/api";

const AXIS = "hsl(var(--muted-foreground))";
const GRID = "hsl(var(--border))";
const PALETTE = ["hsl(var(--chart-1))", "hsl(var(--chart-2))", "hsl(var(--chart-3))",
  "hsl(var(--chart-4))", "hsl(var(--chart-5))", "hsl(var(--muted-foreground))"];

function tip() {
  return {
    contentStyle: { background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))",
      borderRadius: 8, fontSize: 12 },
  };
}

const STYLE_DIMS: { key: string; label: string; fmt?: (v: any) => string }[] = [
  { key: "avg_views_per_post", label: "Avg views", fmt: (v) => Number(v).toLocaleString() },
  { key: "posts_per_day", label: "Posts/day", fmt: (v) => Number(v).toFixed(2) },
  { key: "cta_rate", label: "CTA rate", fmt: (v) => `${(v * 100).toFixed(0)}%` },
  { key: "coupon_rate", label: "Coupon rate", fmt: (v) => `${(v * 100).toFixed(0)}%` },
  { key: "multi_deal_rate", label: "Multi-deal rate", fmt: (v) => `${(v * 100).toFixed(0)}%` },
  { key: "media_rate", label: "Media rate", fmt: (v) => `${(v * 100).toFixed(0)}%` },
  { key: "emoji_rate", label: "Emojis/post", fmt: (v) => Number(v).toFixed(1) },
  { key: "avg_text_len", label: "Caption length", fmt: (v) => Number(v).toFixed(0) },
  { key: "hashtag_rate", label: "Hashtags/post", fmt: (v) => Number(v).toFixed(2) },
  { key: "avg_links", label: "Links/post", fmt: (v) => Number(v).toFixed(2) },
];

const PERIODS: { label: string; value: number | undefined }[] = [
  { label: "7d", value: 7 },
  { label: "30d", value: 30 },
  { label: "90d", value: 90 },
  { label: "All", value: undefined },
];

const btn = (active: boolean) =>
  `cursor-pointer rounded-md px-3 py-1 text-xs font-medium transition-colors ${
    active ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:bg-muted/70"
  }`;

export function Comparison() {
  const [window, setWindow] = useState<number | undefined>(undefined);
  const q = useQuery({
    queryKey: ["comparison", window],
    queryFn: () => api.get<any>(`/api/comparison${window ? `?window=${window}` : ""}`),
  });
  return (
    <div>
      <PageHeader title="You vs competitors" sub="How your channel compares on every dimension the engine measures." />
      <div className="mb-4 flex items-center gap-2">
        <span className="text-xs text-muted-foreground">Period:</span>
        {PERIODS.map((p) => (
          <button key={p.label} className={btn(window === p.value)} onClick={() => setWindow(p.value)}>
            {p.label}
          </button>
        ))}
        {window && (
          <span className="ml-2 text-xs text-muted-foreground">
            · basic stats filtered to last {window}d; style/deal-mix from full window
          </span>
        )}
      </div>
      <Async q={q} rows={2}>
        {(d) => {
          const ents = d.entities || [];
          if (ents.length < 2)
            return <Empty>Not enough competitor data in this window. Try a wider period.</Empty>;

          const entities = ents.slice(0, 6);
          // unique deal types across all entities
          const allTypes = new Set<string>();
          ents.forEach((e: any) => { if (e.deal_mix) Object.keys(e.deal_mix).forEach((t) => allTypes.add(t)); });
          const dealTypes = Array.from(allTypes);

          const dealData = entities.map((e: any) => {
            const row: any = { name: e.is_owned ? "You" : e.name };
            dealTypes.forEach((t) => { row[t] = e.deal_mix?.[t] ?? 0; });
            return row;
          });

          const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
          const wdData = days.map((d) => {
            const row: any = { day: d };
            entities.forEach((e: any) => { row[e.is_owned ? "You" : e.name] = e.weekday_distribution?.[d] ?? 0; });
            return row;
          });

          const hourly = Array.from({ length: 24 }, (_, h) => {
            const row: any = { hour: `${String(h).padStart(2, "0")}` };
            entities.forEach((e: any) => { row[e.is_owned ? "You" : e.name] = e.posts_per_hour_ist?.[h] ?? 0; });
            return row;
          });

          return (
            <div className="space-y-6">
              <div className="rounded-lg border bg-muted/40 p-3 text-xs text-muted-foreground">
                <b>Unavailable:</b> {(d.unavailable || []).join(", ")}. {d.note}
                {d.applied_window && <span> Showing last {d.applied_window}d for basic stats; style/deal-mix from full observation window.</span>}
              </div>

              {/* Style benchmark table */}
              <Card>
                <CardHeader><CardTitle className="text-base">Style &amp; behaviour benchmark</CardTitle>
                  <CardDescription>Side-by-side comparison of every measurable dimension. <span className="text-green-500">Green</span> = best in row.</CardDescription></CardHeader>
                <CardContent className="overflow-x-auto p-0">
                  <Table>
                    <THead>
                      <TR>
                        <TH>Metric</TH>
                        {entities.map((e: any, i: number) => (
                          <TH key={i} className="text-right">{e.is_owned ? "You" : e.name}</TH>
                        ))}
                      </TR>
                    </THead>
                    <TBody>
                      {STYLE_DIMS.map((dim) => {
                        const vals = entities.map((e: any) => e[dim.key]);
                        const numeric = vals.filter((v: any) => v != null && typeof v === "number");
                        const best = numeric.length ? Math.max(...numeric) : null;
                        return (
                          <TR key={dim.key}>
                            <TD className="text-xs text-muted-foreground">{dim.label}</TD>
                            {entities.map((e: any, i: number) => {
                              const v = e[dim.key];
                              const isBest = v != null && best != null && v === best;
                              return (
                                <TD key={i} className={`text-right font-mono text-xs ${isBest ? "font-bold text-green-500" : ""}`}>
                                  {v != null ? (dim.fmt ? dim.fmt(v) : v) : "—"}
                                </TD>
                              );
                            })}
                          </TR>
                        );
                      })}
                    </TBody>
                  </Table>
                </CardContent>
              </Card>

              {/* Deal-mix chart */}
              {dealTypes.length > 0 && (
                <Card>
                  <CardHeader><CardTitle className="text-base">Deal-type mix</CardTitle>
                    <CardDescription>What each channel emphasises — spot gaps your audience might be missing.
                      {ents.some((e: any) => e.deal_mix_note) && <span className="ml-1 text-yellow-500">(full-window data)</span>}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ResponsiveContainer width="100%" height={260}>
                      <BarChart data={dealData} layout="vertical" margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke={GRID} horizontal={false} />
                        <XAxis type="number" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false}
                          tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} />
                        <YAxis type="category" dataKey="name" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={80} />
                        <Tooltip {...tip()} formatter={(v: any) => `${(v * 100).toFixed(1)}%`} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        {dealTypes.map((t, i) => (
                          <Bar key={t} dataKey={t} stackId="a" fill={PALETTE[i % PALETTE.length]}
                            radius={i === dealTypes.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]} />
                        ))}
                      </BarChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>
              )}

              {/* Weekday comparison */}
              <Card>
                <CardHeader><CardTitle className="text-base">Posting by weekday</CardTitle>
                  <CardDescription>When each channel posts — see which days competitors focus on that you don't.</CardDescription></CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={wdData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
                      <XAxis dataKey="day" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} />
                      <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
                      <Tooltip {...tip()} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      {entities.map((e: any, i: number) => (
                        <Bar key={i} dataKey={e.is_owned ? "You" : e.name} fill={PALETTE[i % PALETTE.length]}
                          radius={[4, 4, 0, 0]} />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>

              {/* Hourly timing */}
              <Card>
                <CardHeader><CardTitle className="text-base">Posting activity by hour (IST)</CardTitle>
                  <CardDescription>When each channel posts — spot windows competitors own that you don't.</CardDescription></CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={280}>
                    <LineChart data={hourly} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
                      <XAxis dataKey="hour" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} interval={1} />
                      <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
                      <Tooltip {...tip()} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      {entities.map((e: any, i: number) => (
                        <Line key={i} type="monotone" dataKey={e.is_owned ? "You" : e.name}
                          stroke={PALETTE[i % PALETTE.length]} strokeWidth={e.is_owned ? 2.5 : 1.5} dot={false} />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>

              {/* Signals */}
              {(d.signals || []).length > 0 && (
                <section>
                  <h2 className="mb-3 text-lg font-semibold">Signals &amp; opportunities</h2>
                  <div className="space-y-3">
                    {(d.signals || []).map((s: any, i: number) => (
                      <Card key={i} className="border-l-4 border-l-warning">
                        <CardContent className="p-4">
                          <div className="mb-1 flex items-center gap-2">
                            <Badge variant="warning">{s.type}</Badge>
                            {s.competitor && <Badge>{s.competitor}</Badge>}
                          </div>
                          <p>{s.description}</p>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                </section>
              )}

              {/* Channels compared */}
              <Card>
                <CardHeader><CardTitle className="text-base">Channels compared</CardTitle></CardHeader>
                <CardContent className="space-y-2 text-sm">
                  {ents.map((e: any, i: number) => (
                    <div key={i} className="flex items-center gap-2">
                      {e.is_owned ? <Badge variant="primary">you</Badge> : <Badge>competitor</Badge>}
                      <span className="font-medium">{e.name}</span>
                      <span className="text-muted-foreground">
                        · {e.posts} posts · {e.avg_views_per_post?.toLocaleString() || "?"} avg views · {e.posts_per_day ?? "?"}/day
                        {e.similarity_to_us != null && !e.is_owned && ` · ${(e.similarity_to_us * 100).toFixed(0)}% similar`}
                      </span>
                    </div>
                  ))}
                  {ents.map((e: any) => e.tenure_label).filter(Boolean).length > 0 && (
                    <div className="mt-2 space-y-1 border-t pt-2 text-xs text-muted-foreground">
                      {ents.map((e: any, i: number) => e.tenure_label && (
                        <div key={i} className="flex gap-2">
                          <span className="w-24 shrink-0 font-medium text-foreground/60">{e.is_owned ? "You" : e.name}</span>
                          <span>{e.tenure_label}{e.style_tenure_note ? ` · ${e.style_tenure_note}` : ""}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
