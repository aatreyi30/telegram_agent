import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Async } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { BarsChart, TimelineChart } from "@/components/charts";
import { StatCard } from "@/components/StatCard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/primitives";
import { api } from "@/services/api";
import { fmtNum } from "@/lib/utils";

function ChartCard({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{sub}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

// subtract N days from an ISO date string
function minusDays(iso: string, days: number): string {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

const PRESETS: { key: string; label: string; days: number | null }[] = [
  { key: "30d", label: "30d", days: 30 },
  { key: "90d", label: "90d", days: 90 },
  { key: "6mo", label: "6 mo", days: 182 },
  { key: "12mo", label: "12 mo", days: 365 },
  { key: "all", label: "All", days: null },
];

export function Analytics() {
  const range = useQuery({ queryKey: ["data-range"], queryFn: () => api.get<any>("/api/data-range") });
  const min = range.data?.min as string | undefined;
  const max = range.data?.max as string | undefined;

  const [preset, setPreset] = useState("90d");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");

  // resolve the active [start, end] window (anchored on the latest DATA date, not today)
  const { start, end } = useMemo(() => {
    if (preset === "custom") return { start: customStart || min, end: customEnd || max };
    const p = PRESETS.find((x) => x.key === preset);
    if (!max || !min || !p) return { start: undefined, end: undefined };
    if (p.days === null) return { start: min, end: max };
    return { start: minusDays(max, p.days), end: max };
  }, [preset, customStart, customEnd, min, max]);

  const qs = start && end ? `?start=${start}&end=${end}` : "";
  const q = useQuery({
    queryKey: ["analytics", start, end],
    queryFn: () => api.get<any>(`/api/analytics${qs}`),
    enabled: !!range.data, // wait for the data range before first fetch
  });

  return (
    <div>
      <PageHeader title="Analytics" sub="Built from per-post view counts — the stats available to a channel member." />

      {/* Filter bar */}
      <Card className="mb-4">
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <Button key={p.key} size="sm" variant={preset === p.key ? "default" : "outline"}
                onClick={() => setPreset(p.key)}>
                {p.label}
              </Button>
            ))}
            <Button size="sm" variant={preset === "custom" ? "default" : "outline"} onClick={() => setPreset("custom")}>
              Custom
            </Button>
          </div>
          {preset === "custom" && (
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-1"><Label className="text-xs">From</Label>
                <Input type="date" className="w-40" min={min} max={max}
                  value={customStart || min || ""} onChange={(e) => setCustomStart(e.target.value)} /></div>
              <div className="space-y-1"><Label className="text-xs">To</Label>
                <Input type="date" className="w-40" min={min} max={max}
                  value={customEnd || max || ""} onChange={(e) => setCustomEnd(e.target.value)} /></div>
            </div>
          )}
          <div className="ml-auto text-xs text-muted-foreground">
            {start && end ? `${start} → ${end}` : "…"}{max ? ` · data to ${max}` : ""}
          </div>
        </CardContent>
      </Card>

      <Async q={q} rows={2}>
        {(a) => {
          const win = a.window || {};
          const period = `owned · ${win.start || "?"} → ${win.end || "?"} · n=${fmtNum(win.n)} posts`;
          return (
            <div className="space-y-4">
              <div className="rounded-lg border bg-muted/40 p-3 text-xs text-muted-foreground">
                Telegram's admin-only stats (subscriber growth, reach) require admin rights and aren't
                available yet. Averages are raw views/post (older posts have accumulated longer);
                age-normalized analysis lives on Insights.
              </div>

              {a.total_posts === 0 ? (
                <Card><CardContent className="p-10 text-center text-sm text-muted-foreground">
                  No posts in this date range. Try a wider range or a different window.
                </CardContent></Card>
              ) : (
                <>
                  <div className="grid gap-4 sm:grid-cols-3">
                    <StatCard label="posts in range" value={fmtNum(a.total_posts)} />
                    <StatCard label="total views" value={fmtNum(a.total_views)} />
                    <StatCard label="days covered" value={win.days ?? "—"} />
                  </div>

                  <ChartCard title="Avg views per post over time" sub={period}>
                    <TimelineChart data={a.timeline || []} unit=" views" />
                  </ChartCard>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <ChartCard title="Avg views by hour (IST)" sub="when your posts get the most views">
                      <BarsChart data={a.by_hour || []} unit=" views" />
                    </ChartCard>
                    <ChartCard title="Avg views by weekday (IST)" sub="within the selected range">
                      <BarsChart data={a.by_weekday || []} unit=" views" />
                    </ChartCard>
                  </div>

                  <ChartCard title="Avg views by post type" sub={`which formats perform · ${period}`}>
                    <BarsChart data={a.by_type || []} unit=" views" height={300} />
                  </ChartCard>

                  <ChartCard title="Avg views by merchant (top 10)" sub={`resolved merchants only · ${period}`}>
                    <BarsChart data={a.by_merchant || []} unit=" views" height={300} />
                  </ChartCard>
                </>
              )}
            </div>
          );
        }}
      </Async>
    </div>
  );
}
