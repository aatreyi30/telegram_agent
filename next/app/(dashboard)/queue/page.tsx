"use client";

import { useState } from "react";
import { Async, Empty } from "@/components/Async";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useQueue } from "@/queries/queries";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationLink,
  PaginationPrevious,
  PaginationNext,
  PaginationEllipsis,
} from "@/components/ui/pagination";

function statusVariant(s: string) {
  if (s === "published") return "success" as const;
  if (s === "blocked" || s === "failed") return "destructive" as const;
  return "default" as const;
}

function PageButton({ page, current, onClick }: { page: number; current: number; onClick: (p: number) => void }) {
  return (
    <PaginationItem>
      <div onClick={() => onClick(page)}>
        <PaginationLink isActive={page === current}>{page}</PaginationLink>
      </div>
    </PaginationItem>
  );
}

function renderPageNumbers(current: number, total: number, setPage: (p: number) => void) {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => (
      <PageButton key={i + 1} page={i + 1} current={current} onClick={setPage} />
    ));
  }

  const pages: React.ReactNode[] = [
    <PageButton key={1} page={1} current={current} onClick={setPage} />,
  ];

  if (current > 3) {
    pages.push(<PaginationItem key="es"><PaginationEllipsis /></PaginationItem>);
  }

  const start = Math.max(2, current - 1);
  const end = Math.min(total - 1, current + 1);
  for (let i = start; i <= end; i++) {
    pages.push(<PageButton key={i} page={i} current={current} onClick={setPage} />);
  }

  if (current < total - 2) {
    pages.push(<PaginationItem key="ee"><PaginationEllipsis /></PaginationItem>);
  }

  pages.push(<PageButton key={total} page={total} current={current} onClick={setPage} />);

  return pages;
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
                  <Pagination>
                    <PaginationContent>
                      <PaginationItem>
                        <PaginationPrevious
                          onClick={() => setPage((p) => Math.max(1, p - 1))}
                          className={d.page <= 1 ? "pointer-events-none opacity-50" : "cursor-pointer"}
                        />
                      </PaginationItem>
                      {renderPageNumbers(d.page, d.pages, setPage)}
                      <PaginationItem>
                        <PaginationNext
                          onClick={() => setPage((p) => Math.min(d.pages, p + 1))}
                          className={d.page >= d.pages ? "pointer-events-none opacity-50" : "cursor-pointer"}
                        />
                      </PaginationItem>
                    </PaginationContent>
                  </Pagination>
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
