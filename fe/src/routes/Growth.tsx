import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowDown, ArrowUp, Minus, Users } from "lucide-react";
import { Async } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/services/api";

const AXIS = "hsl(var(--muted-foreground))";
const GRID = "hsl(var(--border))";

function Tip({ active, payload, label, unit }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 text-xs shadow-md">
      <div className="font-medium text-foreground">{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} className="text-muted-foreground">
          {p.name}: <span className="font-semibold text-foreground">{Number(p.value).toLocaleString()}{unit}</span>
        </div>
      ))}
    </div>
  );
}

function StatCard({ icon: Icon, label, value, change, unit }: {
  icon: any; label: string; value: string; change?: number; unit?: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="mt-1 text-2xl font-bold tracking-tight">{value}{unit}</p>
          </div>
          <div className="rounded-lg bg-secondary p-2 text-secondary-foreground">
            <Icon size={20} />
          </div>
        </div>
        {change != null && (
          <div className={`mt-2 flex items-center gap-1 text-xs ${change > 0 ? "text-green-500" : change < 0 ? "text-red-500" : "text-muted-foreground"}`}>
            {change > 0 ? <ArrowUp size={14} /> : change < 0 ? <ArrowDown size={14} /> : <Minus size={14} />}
            <span>{change > 0 ? "+" : ""}{change.toLocaleString()}</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function Growth() {
  const q = useQuery({ queryKey: ["growth"], queryFn: () => api.get<any>("/api/growth") });
  return (
    <div>
      <PageHeader title="Subscriber growth" sub="How your channel's audience is trending over time. Based on participant count snapshots taken each collection cycle." />
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
          const netColor = d.net_change > 0 ? "text-green-500" : d.net_change < 0 ? "text-red-500" : "text-muted-foreground";

          return (
            <div className="space-y-4">
              {/* Stat cards */}
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <StatCard icon={Users} label="Current subscribers" value={d.current?.toLocaleString() || "?"} />
                <StatCard icon={ArrowUp} label="Net change" value={d.net_change > 0 ? `+${d.net_change.toLocaleString()}` : d.net_change.toLocaleString()}
                  change={d.net_change} />
                <Card>
                  <CardContent className="p-4">
                    <p className="text-xs text-muted-foreground">Growth rate</p>
                    <p className={`mt-1 text-2xl font-bold tracking-tight ${netColor}`}>
                      {d.growth_per_day != null ? `${d.growth_per_day > 0 ? "+" : ""}${d.growth_per_day}` : "—"}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">subs / day over {d.span_days} days</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4">
                    <p className="text-xs text-muted-foreground">Total change</p>
                    <p className={`mt-1 text-2xl font-bold tracking-tight ${netColor}`}>
                      {d.growth_rate_pct != null ? `${d.growth_rate_pct > 0 ? "+" : ""}${d.growth_rate_pct}%` : "—"}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">over {d.span_days} days</p>
                  </CardContent>
                </Card>
              </div>

              {/* Subscriber trend chart */}
              <Card>
                <CardHeader><CardTitle className="text-base">Subscriber count</CardTitle>
                  <CardDescription>Daily snapshot values from each collection cycle.</CardDescription></CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={300}>
                    <AreaChart data={daily} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                      <defs>
                        <linearGradient id="fillGrowth" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.5} />
                          <stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0.04} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
                      <XAxis dataKey="date" tick={{ fill: AXIS, fontSize: 10 }} tickLine={false} axisLine={false}
                        minTickGap={60} tickFormatter={(v: string) => v.slice(5)} />
                      <YAxis domain={["auto", "auto"]} tick={{ fill: AXIS, fontSize: 11 }} tickLine={false}
                        axisLine={false} width={60} tickFormatter={(v: number) => v.toLocaleString()} />
                      <Tooltip content={<Tip />} />
                      <Area type="monotone" dataKey="count" stroke="hsl(var(--chart-1))" strokeWidth={2}
                        fill="url(#fillGrowth)" />
                    </AreaChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>

              {/* Daily delta chart */}
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
                      <Tooltip content={<Tip />} />
                      <Bar dataKey="delta" radius={[2, 2, 0, 0]}>
                        {daily.map((_: any, i: number) => (
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
