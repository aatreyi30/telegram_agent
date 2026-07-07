"use client";

import { useState } from "react";
import { Async, Empty } from "@/components/Async";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PagedNav } from "@/components/PagedNav";
import { useQueue } from "@/queries/queries";

function statusVariant(s: string) {
  if (s === "published") return "success" as const;
  if (s === "blocked" || s === "failed") return "destructive" as const;
  return "default" as const;
}

export default function QueuePage() {
  const [page, setPage] = useState(1);
  const q = useQueue(page);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Posting schedule & queue</h1>
        <p className="text-sm text-muted-foreground">
          Each row is one draft queued to one channel at one time (the scheduled_posts table). Sends run via the
          agent and stay gated on channel admin rights.
        </p>
      </div>
      <Async q={q} rows={2}>
        {(d) => (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              {Object.entries(d.counts || {}).map(([k, v]) => (
                <Badge key={k} variant={statusVariant(k)}>{k}: {v}</Badge>
              ))}
              {Object.keys(d.counts || {}).length === 0 && (
                <span className="text-sm text-muted-foreground">Queue is empty.</span>
              )}
              <span className="ml-auto text-xs text-muted-foreground">{d.total} total</span>
            </div>
            {d.items.length ? (
              <>
                <Card>
                  <CardHeader>
                    <div className="h-1 w-10 rounded-full bg-gradient-to-r from-primary to-primary/50 mb-2" />
                    <CardTitle>Queue Items</CardTitle>
                  </CardHeader>
                  <CardContent className="p-0">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="text-right">ID</TableHead>
                          <TableHead>Category</TableHead>
                          <TableHead>Channel</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead>Scheduled (UTC)</TableHead>
                          <TableHead className="text-right">Tries</TableHead>
                          <TableHead>Note</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {d.items.map((r) => (
                          <TableRow key={r.id} className="hover:bg-muted/50">
                            <TableCell className="text-right font-mono text-xs">#{r.id}</TableCell>
                            <TableCell>
                              {r.category ? (
                                <Badge variant="primary">{r.category}</Badge>
                              ) : (
                                <span className="text-muted-foreground">#{r.post_id}</span>
                              )}
                            </TableCell>
                            <TableCell>{r.channel}</TableCell>
                            <TableCell><Badge variant={statusVariant(r.status)}>{r.status}</Badge></TableCell>
                            <TableCell className="text-muted-foreground">{r.scheduled_at}</TableCell>
                            <TableCell className="text-right">{r.attempts}</TableCell>
                            <TableCell className="max-w-sm whitespace-pre-wrap break-words align-top text-xs text-muted-foreground">
                              {r.note || "—"}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
                <PagedNav page={d.page} pages={d.pages} onPageChange={setPage} />
              </>
            ) : (
              <Empty>Queue is empty. Schedule drafts with the CLI (autoschedule) or from the agent.</Empty>
            )}
          </div>
        )}
      </Async>
    </div>
  );
}
