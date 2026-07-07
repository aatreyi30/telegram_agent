"use client";

import { useState } from "react";
import { Async, Empty } from "@/components/Async";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
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
            <div className="flex flex-wrap gap-2">
              {Object.entries(d.counts || {}).map(([k, v]) => (
                <Badge key={k} variant={statusVariant(k)}>{k}: {v}</Badge>
              ))}
              {Object.keys(d.counts || {}).length === 0 && (
                <span className="text-sm text-muted-foreground">Queue is empty.</span>
              )}
            </div>
            {d.items.length ? (
              <>
                <Card>
                  <CardContent className="p-0">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>ID</TableHead>
                          <TableHead>Category</TableHead>
                          <TableHead>Channel</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead>Scheduled (UTC)</TableHead>
                          <TableHead>Tries</TableHead>
                          <TableHead>Note</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {d.items.map((r) => (
                          <TableRow key={r.id}>
                            <TableCell>#{r.id}</TableCell>
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
                            <TableCell>{r.attempts}</TableCell>
                            <TableCell className="max-w-xs truncate text-muted-foreground" title={r.note}>
                              {r.note}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
                <div className="flex items-center justify-between">
                  <p className="text-sm text-muted-foreground">
                    Page {d.page} of {d.pages} &middot; {d.total} total
                  </p>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={d.page <= 1}
                    >
                      Previous
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPage((p) => Math.min(d.pages, p + 1))}
                      disabled={d.page >= d.pages}
                    >
                      Next
                    </Button>
                  </div>
                </div>
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
