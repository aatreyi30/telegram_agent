import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarClock, CheckCircle2, Play, RefreshCw, Search, Square, XCircle } from "lucide-react";
import { PageHeader } from "@/components/AppLayout";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, Select } from "@/components/ui/primitives";
import { api } from "@/services/api";

interface AgentStatus {
  enabled: boolean;
  state: "idle" | "running";
  interval_hours: number;
  last_run: string | null;
  next_run: string | null;
  last_summary: string | null;
  steps: { name: string; status: string; detail: string }[];
  log: string[];
}

const STEP_LABEL: Record<string, string> = {
  collect: "Collect new posts",
  discover: "Discover competitors",
  analyze: "Analyze + refresh plan",
  generate: "Generate drafts",
  schedule: "Schedule into windows",
};

function fmt(ts: string | null) {
  if (!ts) return "—";
  return new Date(ts).toLocaleString();
}

export function Agent() {
  const [interval, setInterval] = useState("6");
  const [busy, setBusy] = useState(false);
  const q = useQuery({
    queryKey: ["agent"],
    queryFn: () => api.get<AgentStatus>("/api/agent"),
    refetchInterval: 2000, // live
  });
  const s = q.data;

  async function call(path: string, body?: unknown) {
    setBusy(true);
    try {
      await api.post(path, body);
      await q.refetch();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Agent"
        sub="The autonomous loop. Every cycle it collects new posts, discovers competitors, re-analyzes and rebuilds the plan, generates fresh relevant drafts, and queues them into your best posting windows. It never sends — publishing stays gated on channel admin rights."
      />

      {/* Controls + status */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">Controls</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted-foreground">Run every</span>
              <Select value={interval} onChange={(e) => setInterval(e.target.value)} className="w-28">
                <option value="1">1 hour</option>
                <option value="6">6 hours</option>
                <option value="12">12 hours</option>
                <option value="24">24 hours</option>
              </Select>
              {!s?.enabled ? (
                <Button disabled={busy} onClick={() => call("/api/agent/start", { interval_hours: Number(interval) })}>
                  <Play size={16} /> Start agent
                </Button>
              ) : (
                <Button variant="destructive" disabled={busy} onClick={() => call("/api/agent/stop")}>
                  <Square size={16} /> Stop agent
                </Button>
              )}
              <Button variant="outline" disabled={busy || s?.state === "running"} onClick={() => call("/api/agent/run-once")}>
                <RefreshCw size={16} /> Run one cycle now
              </Button>
              <Button variant="ghost" disabled={busy} onClick={() => call("/api/agent/discover", { max_add: 5 })}>
                <Search size={16} /> Discover competitors
              </Button>
              <Button variant="ghost" disabled={busy} onClick={() => call("/api/agent/plan-day")}>
                <CalendarClock size={16} /> Plan today's posts
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              “Plan today's posts” fills the day: each peak-views hour gets a category (your preferred first,
              then best available deals), scrapes that category's fresh deals, and queues a draft — no repeats.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">Status</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              {s?.enabled ? <Badge variant="success">running on schedule</Badge> : <Badge>off</Badge>}
              {s?.state === "running" && <Badge variant="primary">cycle in progress…</Badge>}
            </div>
            <div className="text-muted-foreground">Interval: every {s?.interval_hours ?? "—"}h</div>
            <div className="text-muted-foreground">Last run: {fmt(s?.last_run ?? null)} {s?.last_summary ? `· ${s.last_summary}` : ""}</div>
            <div className="text-muted-foreground">Next run: {fmt(s?.next_run ?? null)}</div>
          </CardContent>
        </Card>
      </div>

      {/* Per-step results */}
      {s?.steps && s.steps.length > 0 && (
        <Card className="mt-4">
          <CardHeader><CardTitle className="text-base">Last cycle steps</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {s.steps.map((st, i) => (
              <div key={i} className="flex items-start gap-2 border-b pb-2 last:border-0 last:pb-0">
                {st.status === "ok" ? (
                  <CheckCircle2 className="mt-0.5 shrink-0 text-success" size={18} />
                ) : (
                  <XCircle className="mt-0.5 shrink-0 text-destructive" size={18} />
                )}
                <div>
                  <div className="text-sm font-medium">{STEP_LABEL[st.name] || st.name}</div>
                  {st.detail && <div className="text-xs text-muted-foreground">{st.detail}</div>}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Live log */}
      <Card className="mt-4">
        <CardHeader><CardTitle className="text-base">Live log</CardTitle></CardHeader>
        <CardContent>
          <pre className="max-h-72 overflow-auto rounded-lg border bg-background p-3 text-xs leading-relaxed text-muted-foreground">
            {(s?.log || []).join("\n") || "Agent idle. Start it, or run one cycle now."}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}
