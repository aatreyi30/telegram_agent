import { useState } from "react";
import { Async, Empty } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { Badge } from "@/components/ui/primitives";
import { Card, CardContent } from "@/components/ui/card";
import { Pagination } from "@/components/ui/pagination";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useQueue } from "@/queries/queries";

function statusVariant(s: string) {
  if (s === "published") return "success" as const;
  if (s === "blocked" || s === "failed") return "destructive" as const;
  return "default" as const;
}

export function Queue() {
  const [page, setPage] = useState(1);
  const q = useQueue(page);

  return (
    <div>
      <PageHeader
        title="Posting schedule & queue"
        sub="Each row is one draft queued to one channel at one time (the scheduled_posts table). Sends run via the agent and stay gated on channel admin rights."
      />
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
                      <THead>
                        <TR><TH>ID</TH><TH>Category</TH><TH>Channel</TH><TH>Status</TH><TH>Scheduled (UTC)</TH><TH>Tries</TH><TH>Note</TH></TR>
                      </THead>
                      <TBody>
                        {d.items.map((r) => (
                          <TR key={r.id}>
                            <TD>#{r.id}</TD>
                            <TD>{r.category ? <Badge variant="primary">{r.category}</Badge> : <span className="text-muted-foreground">#{r.post_id}</span>}</TD>
                            <TD>{r.channel}</TD>
                            <TD><Badge variant={statusVariant(r.status)}>{r.status}</Badge></TD>
                            <TD className="text-muted-foreground">{r.scheduled_at}</TD>
                            <TD>{r.attempts}</TD>
                            <TD className="max-w-xs truncate text-muted-foreground" title={r.note}>{r.note}</TD>
                          </TR>
                        ))}
                      </TBody>
                    </Table>
                  </CardContent>
                </Card>
                <Pagination page={d.page} pages={d.pages} total={d.total} onPage={setPage} />
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
