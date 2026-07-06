import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Play, RefreshCw, Square } from "lucide-react";
import { PageHeader } from "@/components/AppLayout";
import { Async } from "@/components/Async";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/primitives";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/services/api";

const PRIO: Record<string, "destructive" | "warning" | "default"> = {
  critical: "destructive", high: "warning", medium: "default", low: "default",
};
const STATUS: Record<string, "success" | "warning" | "destructive" | "default"> = {
  success: "success", limited: "warning", failed: "destructive", retrying: "warning",
};

function ago(ts?: string | null) {
  if (!ts) return "never";
  return new Date(ts).toLocaleString();
}

export function Schedulers() {
  const [busy, setBusy] = useState(false);
  const q = useQuery({ queryKey: ["schedulers"], queryFn: () => api.get<any>("/api/schedulers"), refetchInterval: 4000 });
  const logs = useQuery({ queryKey: ["sched-logs"], queryFn: () => api.get<any[]>("/api/schedulers/logs?limit=25"), refetchInterval: 4000 });

  async function call(path: string) {
    setBusy(true);
    try { await api.post(path); await q.refetch(); await logs.refetch(); }
    finally { setBusy(false); }
  }

  return (
    <div>
      <PageHeader
        title="Schedulers"
        sub="20 background jobs that keep everything fresh — sync, analysis, reports, deal & URL health, queue publishing, cleanup. OFF by default (the fast cadences hit live Telegram); start it on an always-on server. Each run is logged with retries (5→15→30 min)."
      />

      <Async q={q} rows={2}>
        {(s) => (
          <>
            <Card className="mb-4">
              <CardContent className="flex flex-wrap items-center gap-3 p-4">
                {s.enabled
                  ? <Badge variant="success">running — {s.count} jobs scheduled</Badge>
                  : <Badge>stopped</Badge>}
                {!s.enabled
                  ? <Button disabled={busy} onClick={() => call("/api/schedulers/start")}><Play size={16} /> Start all</Button>
                  : <Button variant="destructive" disabled={busy} onClick={() => call("/api/schedulers/stop")}><Square size={16} /> Stop all</Button>}
                <span className="text-xs text-muted-foreground">Reactions / reach / engagement need admin or a bot — those jobs log “limited”.</span>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle className="text-base">Jobs</CardTitle></CardHeader>
              <CardContent className="p-0">
                <Table>
                  <THead><TR><TH>Job</TH><TH>Cadence</TH><TH>Priority</TH><TH>Last run</TH><TH>Result</TH><TH></TH></TR></THead>
                  <TBody>
                    {s.jobs.map((j: any) => (
                      <TR key={j.key}>
                        <TD className="font-medium">{j.name}</TD>
                        <TD className="text-muted-foreground">{j.cadence}</TD>
                        <TD><Badge variant={PRIO[j.priority]}>{j.priority}</Badge></TD>
                        <TD className="text-muted-foreground text-xs">{ago(j.last?.at)}</TD>
                        <TD>
                          {j.last
                            ? <><Badge variant={STATUS[j.last.status] || "default"}>{j.last.status}</Badge>
                                <div className="text-xs text-muted-foreground">{j.last.detail}</div></>
                            : <span className="text-xs text-muted-foreground">—</span>}
                        </TD>
                        <TD>
                          <Button variant="ghost" size="sm" disabled={busy}
                            onClick={() => call(`/api/schedulers/run/${j.key}`)}>
                            <RefreshCw size={14} /> Run
                          </Button>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </CardContent>
            </Card>

            <Card className="mt-4">
              <CardHeader><CardTitle className="text-base">Recent run log</CardTitle></CardHeader>
              <CardContent className="p-0">
                <Async q={logs} rows={1}>
                  {(rows) => (
                    <Table>
                      <THead><TR><TH>When</TH><TH>Job</TH><TH>Status</TH><TH>Detail</TH><TH>ms</TH></TR></THead>
                      <TBody>
                        {rows.map((r, i) => (
                          <TR key={i}>
                            <TD className="text-xs text-muted-foreground">{ago(r.at)}</TD>
                            <TD>{r.key}</TD>
                            <TD><Badge variant={STATUS[r.status] || "default"}>{r.status}</Badge></TD>
                            <TD className="text-muted-foreground">{r.detail || r.error}</TD>
                            <TD className="text-muted-foreground">{r.duration_ms}</TD>
                          </TR>
                        ))}
                      </TBody>
                    </Table>
                  )}
                </Async>
              </CardContent>
            </Card>
          </>
        )}
      </Async>
    </div>
  );
}
