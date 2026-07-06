import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Async, Empty } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { StatCard } from "@/components/StatCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/primitives";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/services/api";
import { fmtNum, fmtPct } from "@/lib/utils";

export function DayView() {
  // bound + default to the collected data range (today may be after the last collection)
  const range = useQuery({ queryKey: ["data-range"], queryFn: () => api.get<any>("/api/data-range") });
  const min = range.data?.min as string | undefined;
  const max = range.data?.max as string | undefined;

  const [date, setDate] = useState<string>("");        // "" -> backend uses latest data date
  const [applied, setApplied] = useState<string>("");
  const q = useQuery({
    queryKey: ["day", applied],
    queryFn: () => api.get<any>(`/api/day${applied ? `?date=${applied}` : ""}`),
    enabled: !!range.data,
  });

  // once we know the range (and the user hasn't picked yet), reflect the resolved day in the picker
  const shownDate = date || q.data?.date || max || "";

  return (
    <div>
      <PageHeader title="Day view" sub="What happened on a specific date (IST). Defaults to your latest collected day." />
      <div className="mb-2 flex items-end gap-2">
        <Input type="date" value={shownDate} min={min} max={max}
          onChange={(e) => setDate(e.target.value)} className="w-48" />
        <Button onClick={() => setApplied(date || max || "")}>Show day</Button>
        {max && <Button variant="outline" onClick={() => { setDate(""); setApplied(""); }}>Latest</Button>}
      </div>
      {max && <p className="mb-4 text-xs text-muted-foreground">Collected data runs {min} → {max} (IST).</p>}

      <Async q={q} rows={2}>
        {(d) =>
          !d.available ? (
            <Empty>{d.note || "No posts on this date."}</Empty>
          ) : (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-3">
                <StatCard label="posts" value={fmtNum(d.posts)} />
                <StatCard label="total views" value={fmtNum(d.total_views)} />
                <StatCard
                  label="avg views/post"
                  value={fmtNum(d.avg_views_per_post)}
                  sub={d.vs_baseline?.views_delta_pct != null ? `${fmtPct(d.vs_baseline.views_delta_pct, true)} vs 30-day avg` : undefined}
                />
              </div>

              <Card>
                <CardHeader><CardTitle className="text-base">Top posts that day</CardTitle></CardHeader>
                <CardContent className="p-0">
                  <Table>
                    <THead><TR><TH>Views</TH><TH>Type</TH><TH>Merchant</TH><TH>Preview</TH></TR></THead>
                    <TBody>
                      {d.top_posts.map((p: any, i: number) => (
                        <TR key={i}>
                          <TD className="font-semibold">{fmtNum(p.views)}</TD>
                          <TD>{p.type}</TD>
                          <TD>{p.merchant}</TD>
                          <TD className="text-muted-foreground">{p.preview}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </CardContent>
              </Card>

              <Card>
                <CardHeader><CardTitle className="text-base">Mix</CardTitle></CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <div><span className="font-medium">Post types:</span>{" "}
                    {d.type_mix.map((t: any) => `${t[0]} ×${t[1]}`).join(", ") || "—"}</div>
                  <div><span className="font-medium">Merchants:</span>{" "}
                    {d.merchant_mix.map((m: any) => `${m[0]} ×${m[1]}`).join(", ") || "—"}</div>
                  <p className="text-xs text-muted-foreground">
                    Compared against {d.baseline.window}: {d.baseline.avg_posts_per_day} posts/day,
                    {" "}{fmtNum(d.baseline.avg_views_per_post)} avg views/post.
                  </p>
                </CardContent>
              </Card>
            </div>
          )
        }
      </Async>
    </div>
  );
}
