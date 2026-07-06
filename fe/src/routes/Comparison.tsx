import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Async, Empty } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/primitives";
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

function BarCompare({ data, dataKey, unit }: { data: any[]; dataKey: string; unit?: string }) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="name" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false}
          interval={0} angle={data.length > 4 ? -20 : 0} height={data.length > 4 ? 50 : 30}
          textAnchor={data.length > 4 ? "end" : "middle"} />
        <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={44} />
        <Tooltip {...tip()} formatter={(v: any) => [`${Number(v).toLocaleString()}${unit || ""}`, dataKey]} />
        <Bar dataKey={dataKey} radius={[4, 4, 0, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.is_owned ? "hsl(var(--chart-1))" : "hsl(var(--chart-2))"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Comparison() {
  const q = useQuery({ queryKey: ["comparison"], queryFn: () => api.get<any>("/api/comparison") });
  return (
    <div>
      <PageHeader
        title="You vs competitors"
        sub="How your channel compares on the signals we can measure for both sides. Updates as new posts are collected from your channel and the competitors."
      />
      <Async q={q} rows={2}>
        {(d) => {
          const ents = d.entities || [];
          if (ents.length < 2)
            return <Empty>Not enough competitor data yet. Run competitor discovery + sync (Agent / Schedulers), then re-check.</Empty>;

          const bars = ents.map((e: any) => ({
            name: e.is_owned ? "You" : e.name, is_owned: e.is_owned,
            avg_views_per_post: e.avg_views_per_post, posts_per_day: e.posts_per_day,
          }));
          // posts-per-hour: one row per hour, one series per entity
          const hourly = Array.from({ length: 24 }, (_, h) => {
            const row: any = { hour: `${String(h).padStart(2, "0")}` };
            ents.forEach((e: any) => { row[e.is_owned ? "You" : e.name] = e.posts_per_hour_ist?.[h] ?? 0; });
            return row;
          });

          return (
            <div className="space-y-4">
              <div className="rounded-lg border bg-muted/40 p-3 text-xs text-muted-foreground">
                <b>Unavailable:</b> {(d.unavailable || []).join(", ")}. {d.note}
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <Card>
                  <CardHeader><CardTitle className="text-base">Avg views per post</CardTitle>
                    <CardDescription>Your reach-per-post vs competitors (blue = you)</CardDescription></CardHeader>
                  <CardContent><BarCompare data={bars} dataKey="avg_views_per_post" unit=" views" /></CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-base">Posts per day</CardTitle>
                    <CardDescription>Posting cadence over each channel's observed window</CardDescription></CardHeader>
                  <CardContent><BarCompare data={bars} dataKey="posts_per_day" /></CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader><CardTitle className="text-base">Posting activity by hour (IST)</CardTitle>
                  <CardDescription>When each channel posts — spot windows competitors own that you don't</CardDescription></CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={280}>
                    <LineChart data={hourly} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
                      <XAxis dataKey="hour" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} interval={1} />
                      <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
                      <Tooltip {...tip()} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      {ents.map((e: any, i: number) => (
                        <Line key={i} type="monotone" dataKey={e.is_owned ? "You" : e.name}
                          stroke={PALETTE[i % PALETTE.length]} strokeWidth={e.is_owned ? 2.5 : 1.5} dot={false} />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>

              <Card>
                <CardHeader><CardTitle className="text-base">Channels compared</CardTitle></CardHeader>
                <CardContent className="space-y-1 text-sm">
                  {ents.map((e: any, i: number) => (
                    <div key={i} className="flex items-center gap-2">
                      {e.is_owned ? <Badge variant="primary">you</Badge> : <Badge>competitor</Badge>}
                      <span className="font-medium">{e.name}</span>
                      <span className="text-muted-foreground">
                        · {e.posts} posts over {e.window_days}d · {e.avg_views_per_post?.toLocaleString()} avg views · {e.posts_per_day}/day
                      </span>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
