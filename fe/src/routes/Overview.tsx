import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileText, Radio, Send, Users2, XCircle } from "lucide-react";
import { Async } from "@/components/Async";
import { JobRunner } from "@/components/JobRunner";
import { PageHeader } from "@/components/AppLayout";
import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/ui/primitives";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/services/api";
import { fmtNum } from "@/lib/utils";

export function Overview() {
  const qc = useQueryClient();
  const ov = useQuery({ queryKey: ["overview"], queryFn: () => api.get<any>("/api/overview") });
  const ins = useQuery({ queryKey: ["insights"], queryFn: () => api.get<any>("/api/insights") });

  return (
    <div>
      <PageHeader title="Overview" sub="What to do today, and the state of your channel." />

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

      <h2 className="mb-3 mt-8 text-lg font-semibold">Do today</h2>
      <Async q={ins}>
        {(d) => (
          <div className="space-y-3">
            {(d.recommendations || []).slice(0, 5).map((r: any, i: number) => (
              <Card key={i} className="border-l-4 border-l-primary">
                <CardContent className="p-4">
                  <div className="mb-1 flex items-center gap-2">
                    {r.priority != null && <Badge variant="primary">P{r.priority}</Badge>}
                    {r.category && <Badge>{r.category}</Badge>}
                  </div>
                  <p className="font-medium">{r.recommendation}</p>
                  {r.reasoning && <p className="mt-1 text-sm text-muted-foreground">{r.reasoning}</p>}
                  {r.expected_outcome && (
                    <p className="mt-1 text-sm text-muted-foreground">Expected: {r.expected_outcome}</p>
                  )}
                </CardContent>
              </Card>
            ))}
            {(d.recommendations || []).length === 0 && (
              <p className="text-sm text-muted-foreground">No recommendations yet — run the pipeline.</p>
            )}
          </div>
        )}
      </Async>

      <div className="mt-8 grid gap-4 lg:grid-cols-2">
        <JobRunner
          onDone={() => {
            qc.invalidateQueries();
          }}
        />
        <Async q={ov} rows={1}>
          {(o) => (
            <Card>
              <CardHeader>
                <CardTitle>Publishing readiness</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {(o.publishing_gates || []).map((g: any, i: number) => (
                  <div key={i} className="flex items-start gap-3 border-b pb-3 last:border-0 last:pb-0">
                    {g.ok ? (
                      <CheckCircle2 className="mt-0.5 shrink-0 text-success" size={18} />
                    ) : (
                      <XCircle className="mt-0.5 shrink-0 text-destructive" size={18} />
                    )}
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
    </div>
  );
}
