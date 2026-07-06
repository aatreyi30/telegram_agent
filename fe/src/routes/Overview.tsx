import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Bot, CheckCircle2, FileText, Radio, Send, Users2, XCircle } from "lucide-react";
import { Async } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/services/api";
import { fmtNum } from "@/lib/utils";

// Overview = status at a glance + the single next action. Detail lives elsewhere
// (Insights = analysis, Plan = the plan, Agent = run controls) — no repetition.
export function Overview() {
  const ov = useQuery({ queryKey: ["overview"], queryFn: () => api.get<any>("/api/overview") });
  const ins = useQuery({ queryKey: ["insights"], queryFn: () => api.get<any>("/api/insights") });
  const agent = useQuery({ queryKey: ["agent"], queryFn: () => api.get<any>("/api/agent") });

  return (
    <div>
      <PageHeader
        title="Overview"
        sub="Your channel at a glance — status now and the one thing to do next. Full analysis lives in Insights; the plan lives in Plan; run controls are in Agent."
      />

      <Async q={ov} rows={1}>
        {(o) => {
          const queued = Object.values(o.queue_counts || {}).reduce((a: number, b: any) => a + b, 0);
          return (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="posts collected" value={fmtNum(o.posts)} icon={<Radio size={20} />} />
              <StatCard label="competitors tracked" value={fmtNum(o.competitors)} icon={<Users2 size={20} />} />
              <StatCard label="drafts ready" value={fmtNum(o.drafts)} icon={<FileText size={20} />} />
              <StatCard label="queued to post" value={fmtNum(queued)} icon={<Send size={20} />} />
            </div>
          );
        }}
      </Async>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="border-l-4 border-l-primary lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-base">Top priority right now</CardTitle>
            <Link to="/app/insights"><Button variant="ghost" size="sm">All insights <ArrowRight size={14} /></Button></Link>
          </CardHeader>
          <CardContent>
            <Async q={ins} rows={1}>
              {(d) => {
                const r = (d.recommendations || [])[0];
                if (!r) return <p className="text-sm text-muted-foreground">No recommendations yet — run the agent.</p>;
                return (
                  <div>
                    <div className="mb-1 flex items-center gap-2">
                      {r.priority != null && <Badge variant="primary">P{r.priority}</Badge>}
                      {r.category && <Badge>{r.category}</Badge>}
                    </div>
                    <p className="font-medium">{r.recommendation}</p>
                    {r.reasoning && <p className="mt-1 text-sm text-muted-foreground">{r.reasoning}</p>}
                  </div>
                );
              }}
            </Async>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base"><Bot size={16} /> Agent</CardTitle>
            <Link to="/app/agent"><Button variant="ghost" size="sm">Open <ArrowRight size={14} /></Button></Link>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            <Async q={agent} rows={1}>
              {(a) => (
                <>
                  <div>
                    {a.enabled ? <Badge variant="success">running · every {a.interval_hours}h</Badge> : <Badge>off</Badge>}
                    {a.state === "running" && <Badge variant="primary" className="ml-1">cycle…</Badge>}
                  </div>
                  <div className="text-muted-foreground">Last: {a.last_summary || "—"}</div>
                  <div className="text-muted-foreground">Next: {a.next_run ? new Date(a.next_run).toLocaleString() : "—"}</div>
                </>
              )}
            </Async>
          </CardContent>
        </Card>
      </div>

      <Async q={ov} rows={1}>
        {(o) => (
          <Card className="mt-4">
            <CardHeader><CardTitle className="text-base">Publishing readiness</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {(o.publishing_gates || []).map((g: any, i: number) => (
                <div key={i} className="flex items-start gap-3 border-b pb-3 last:border-0 last:pb-0">
                  {g.ok ? <CheckCircle2 className="mt-0.5 shrink-0 text-success" size={18} />
                        : <XCircle className="mt-0.5 shrink-0 text-destructive" size={18} />}
                  <div>
                    <div className="flex items-center gap-2 text-sm font-medium">
                      {g.name} {g.ok ? <Badge variant="success">ready</Badge> : <Badge variant="destructive">blocked</Badge>}
                    </div>
                    <p className="text-xs text-muted-foreground">{g.detail}</p>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        )}
      </Async>
    </div>
  );
}
