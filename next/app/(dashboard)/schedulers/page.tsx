"use client";

import { Async, Empty } from "@/components/Async";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useSchedulerRuns } from "@/queries/queries";

function statusVariant(s: string | null) {
  if (s === "success") return "success" as const;
  if (s === "failed") return "destructive" as const;
  if (s === "limited") return "warning" as const;
  if (s === "retrying") return "secondary" as const;
  return "outline" as const;
}

function formatAt(iso: string | null) {
  if (!iso) return "never";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export default function SchedulersPage() {
  const q = useSchedulerRuns();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Schedulers</h1>
        <p className="text-sm text-muted-foreground">
          The 20+ background jobs that keep data fresh — cadence, last run status, and whether a job is overdue.
        </p>
      </div>
      <Async q={q}>
        {(d) => (
          d.jobs.length ? (
            <Card>
              <CardHeader>
                <div className="h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50 mb-2" />
                <CardTitle>Jobs</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Job</TableHead>
                      <TableHead>Cadence</TableHead>
                      <TableHead>Priority</TableHead>
                      <TableHead>Last status</TableHead>
                      <TableHead>Last run</TableHead>
                      <TableHead>Detail</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.jobs.map((j) => (
                      <TableRow key={j.key} className="hover:bg-muted/50">
                        <TableCell>{j.name}</TableCell>
                        <TableCell className="text-muted-foreground">{j.cadence}</TableCell>
                        <TableCell><Badge variant="outline">{j.priority}</Badge></TableCell>
                        <TableCell>
                          <div className="flex flex-wrap items-center gap-1">
                            <Badge variant={statusVariant(j.last_status)}>{j.last_status ?? "never run"}</Badge>
                            {j.overdue === true && <Badge variant="destructive">overdue</Badge>}
                          </div>
                        </TableCell>
                        <TableCell className="text-muted-foreground">{formatAt(j.last_started_at)}</TableCell>
                        <TableCell className="max-w-sm whitespace-pre-wrap break-words align-top text-xs text-muted-foreground">
                          {j.last_error || j.last_detail || "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          ) : (
            <Empty>No scheduler jobs registered.</Empty>
          )
        )}
      </Async>
    </div>
  );
}
