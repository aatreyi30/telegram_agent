"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowUp, Users } from "lucide-react";
import { Async } from "@/components/Async";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { StatCard } from "@/components/StatCard";
import { TimelineChart } from "@/components/charts";
import { useGrowth } from "@/queries/queries";
import { CHART_AXIS_COLOR as AXIS, CHART_GRID_COLOR as GRID } from "@/constants/charts";
import type { GrowthDailyPoint } from "@/types/api";

export default function GrowthPage() {
  const q = useGrowth();
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Subscriber growth</h1>
        <p className="text-sm text-muted-foreground">How your channel's audience is trending over time. Based on participant count snapshots taken each collection cycle.</p>
      </div>
      <Async q={q}>
        {(d) => {
          if (!d.available) {
            return (
              <Card>
                <CardContent className="p-6 text-center text-sm text-muted-foreground">
                  <Users size={32} className="mx-auto mb-2 opacity-30" />
                  <p>{d.reason || "Growth data not yet available."}</p>
                  <p className="mt-1 text-xs">Snapshots are taken automatically as new posts are collected. Check back after the next collection cycle.</p>
                </CardContent>
              </Card>
            );
          }

          const daily = d.daily || [];
          const timelineData = daily.map((p: GrowthDailyPoint) => ({ label: String(p.date).slice(5), count: p.count, delta: p.delta }));
          return (
            <div className="space-y-4">
              {/* Stat cards */}
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <StatCard
                  icon={<Users size={20} />}
                  label="Current subscribers"
                  value={d.current?.toLocaleString() || "?"}
                  trend={d.growth_rate_pct != null ? { value: d.growth_rate_pct, label: "vs first snapshot" } : undefined}
                />
                <StatCard
                  icon={<ArrowUp size={20} />}
                  label="Net change"
                  value={d.net_change > 0 ? `+${d.net_change.toLocaleString()}` : d.net_change.toLocaleString()}
                  trend={d.growth_rate_pct != null ? { value: d.growth_rate_pct } : undefined}
                />
                <StatCard
                  label="Growth rate"
                  value={d.growth_per_day != null ? `${d.growth_per_day > 0 ? "+" : ""}${d.growth_per_day}` : "—"}
                  sub={`subs / day over ${d.span_days} days`}
                />
                <StatCard
                  label="Total change"
                  value={d.growth_rate_pct != null ? `${d.growth_rate_pct > 0 ? "+" : ""}${d.growth_rate_pct}%` : "—"}
                  sub={`over ${d.span_days} days`}
                />
              </div>

              {/* Subscriber trend chart */}
              <Card>
                <CardHeader><CardTitle className="text-base">Subscriber count</CardTitle>
                  <CardDescription>Daily snapshot values from each collection cycle.</CardDescription></CardHeader>
                <CardContent>
                  <TimelineChart data={timelineData} dataKey="count" />
                </CardContent>
              </Card>

              {/* Daily delta chart — kept as a raw recharts BarChart (not the shared BarsChart) so each
                  bar can be colored green/red by sign; BarsChart only supports a single fill color. */}
              <Card>
                <CardHeader><CardTitle className="text-base">Daily change</CardTitle>
                  <CardDescription>Subscriber gain/loss between snapshots. Green = gained, red = lost.</CardDescription></CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={daily} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
                      <XAxis dataKey="date" tick={{ fill: AXIS, fontSize: 10 }} tickLine={false} axisLine={false}
                        minTickGap={60} tickFormatter={(v: string) => v.slice(5)} />
                      <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
                      <Tooltip
                        contentStyle={{ backgroundColor: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                        labelStyle={{ color: "hsl(var(--foreground))", fontWeight: 500 }}
                        formatter={(value: number) => [value.toLocaleString(), "Change"]}
                      />
                      <Bar dataKey="delta" radius={[2, 2, 0, 0]}>
                        {daily.map((_: GrowthDailyPoint, i: number) => (
                          <Cell key={i} fill={(daily[i]?.delta || 0) >= 0 ? "hsl(var(--chart-1))" : "hsl(var(--destructive))"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
