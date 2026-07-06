import { useEffect, useRef, useState } from "react";
import { Play, Sparkles, Square } from "lucide-react";
import { api } from "@/services/api";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

interface JobStatus {
  state: "idle" | "running" | "done" | "error" | "stopped";
  log: string[];
  stopping?: boolean;
}

export function JobRunner({ onDone }: { onDone?: () => void }) {
  const [job, setJob] = useState<JobStatus>({ state: "idle", log: [] });
  const timer = useRef<number | null>(null);
  const logRef = useRef<HTMLPreElement>(null);

  function poll() {
    if (timer.current) return;
    timer.current = window.setInterval(async () => {
      try {
        const j = await api.get<JobStatus>("/api/job");
        setJob(j);
        if (j.state !== "running") {
          clearInterval(timer.current!);
          timer.current = null;
          if (j.state === "done") onDone?.();
        }
      } catch {
        clearInterval(timer.current!);
        timer.current = null;
      }
    }, 1000);
  }

  useEffect(() => {
    // resume polling if a job is already running when mounted
    api.get<JobStatus>("/api/job").then((j) => {
      setJob(j);
      if (j.state === "running") poll();
    });
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [job.log]);

  async function run(path: string) {
    await api.post(path);
    poll();
  }
  async function stop() {
    await api.post("/run/stop");
  }

  const running = job.state === "running";
  return (
    <Card>
      <CardHeader>
        <CardTitle>Run the agent</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => run("/run/pipeline")} disabled={running}>
            <Play size={16} /> Run full pipeline
          </Button>
          <Button variant="secondary" onClick={() => run("/run/generate-live")} disabled={running}>
            <Sparkles size={16} /> Generate from today's deals
          </Button>
          <Button variant="outline" onClick={stop} disabled={!running}>
            <Square size={16} /> Stop
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Pipeline: normalize → classify → merchant/competitor intel → learn → growth → reason → plan → AI briefing.
          Nothing is published.
        </p>
        {(job.log.length > 0 || running) && (
          <pre
            ref={logRef}
            className="max-h-56 overflow-auto rounded-lg border bg-background p-3 text-xs leading-relaxed text-muted-foreground"
          >
            {job.log.join("\n") || "Starting…"}
          </pre>
        )}
      </CardContent>
    </Card>
  );
}
