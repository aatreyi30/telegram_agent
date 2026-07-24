"use client";

import { Async, Empty } from "@/components/Async";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { useSchedulerRuns } from "@/queries/queries";
import { relative, istDateTime } from "@/lib/format";

export default function SchedulersPage() {
  const q = useSchedulerRuns();

  return (
    <div className="space-y-5">
      <PageHeader
        title="System health"
        subtitle="The behind-the-scenes jobs that keep your data fresh and your posts going out. You shouldn't need this often."
      />
      <Async q={q}>
        {(d) => {
          if (!d.jobs.length) return <Empty>No background jobs registered yet.</Empty>;
          const attention = d.jobs.filter((j) => j.overdue === true || j.last_status === "failed");
          const allOk = attention.length === 0;
          return (
            <div className="space-y-4">
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <div className={`h-2 w-2 rounded-full ${allOk ? "bg-green-500" : "bg-orange-400"}`} />
                    <CardTitle className="text-base">{allOk ? "All systems fresh" : `${attention.length} job${attention.length === 1 ? "" : "s"} need attention`}</CardTitle>
                    <Badge variant={allOk ? "success" : "warning"} className="text-xs">{d.jobs.length - attention.length}/{d.jobs.length} healthy</Badge>
                  </div>
                  <CardDescription>
                    {allOk ? "Every job ran on schedule." : "Some jobs are overdue or failed — data below them may be stale until they recover."}
                  </CardDescription>
                </CardHeader>
                <CardContent className="p-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Job</TableHead>
                        <TableHead>Schedule</TableHead>
                        <TableHead>Last run</TableHead>
                        <TableHead>Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {d.jobs.map((j) => (
                        <TableRow key={j.key} className="hover:bg-muted/50">
                          <TableCell className="font-medium">{j.name}</TableCell>
                          <TableCell className="text-muted-foreground">{j.cadence}</TableCell>
                          <TableCell className="text-muted-foreground">
                            {j.last_started_at ? (
                              <Tooltip>
                                <TooltipTrigger className="cursor-default">{relative(j.last_started_at)}</TooltipTrigger>
                                <TooltipContent>{istDateTime(j.last_started_at)} IST</TooltipContent>
                              </Tooltip>
                            ) : "Never run"}
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-wrap items-center gap-1">
                              {j.last_error ? (
                                <Tooltip>
                                  <TooltipTrigger><StatusPill status={j.last_status} /></TooltipTrigger>
                                  <TooltipContent className="max-w-sm whitespace-pre-wrap break-words">{j.last_error}</TooltipContent>
                                </Tooltip>
                              ) : (
                                <StatusPill status={j.last_status} />
                              )}
                              {j.overdue === true && <Badge variant="warning">Overdue</Badge>}
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
