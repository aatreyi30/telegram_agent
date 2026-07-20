"use client";

import { useState } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { Clock01Icon, Sent02Icon } from "@hugeicons/core-free-icons";
import { Async, Empty } from "@/components/Async";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { PageHeader } from "@/components/PageHeader";
import { PostPreview } from "@/components/PostPreview";
import { StatusPill, StatusCounts } from "@/components/StatusPill";
import { MoneyBadge } from "@/components/MoneyBadge";
import { PagedNav } from "@/components/PagedNav";
import { useQueue } from "@/queries/queries";
import { postTypeLabel, merchantLabel, istDateTime, relative } from "@/lib/format";
import type { QueueItem } from "@/types/api";

function firstLine(text?: string | null): string {
  if (!text) return "";
  const line = text.split("\n").find((l) => l.trim());
  return (line || "").replace(/\*\*|__|`/g, "").trim();
}

function TypeMerchant({ r }: { r: QueueItem }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <Badge variant="secondary" className="font-medium">{postTypeLabel(r.post_type)}</Badge>
      {r.merchant && <span className="text-muted-foreground">{merchantLabel(r.merchant)}</span>}
    </span>
  );
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <span className="shrink-0 text-xs text-muted-foreground">{label}</span>
      <span className="text-right text-sm">{children}</span>
    </div>
  );
}

export default function QueuePage() {
  const [page, setPage] = useState(1);
  const [active, setActive] = useState<QueueItem | null>(null);
  const q = useQueue(page);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Posting schedule"
        subtitle="Every post lined up to go out, newest first. Click a row to see exactly what will be sent."
      />

      <Async q={q} rows={3}>
        {(d) => (
          <div className="space-y-4">
            {/* status summary */}
            <div className="flex flex-wrap items-center gap-2">
              <StatusCounts counts={d.counts} />
              {Object.keys(d.counts || {}).length === 0 && (
                <span className="text-sm text-muted-foreground">Nothing scheduled.</span>
              )}
              <span className="ml-auto text-xs text-muted-foreground">{d.total} total</span>
            </div>

            {d.items.length ? (
              <>
                <Card className="overflow-hidden py-0">
                  <CardContent className="p-0">
                    <ul className="divide-y divide-border">
                      {d.items.map((r) => (
                        <li key={r.id}>
                          <button
                            onClick={() => setActive(r)}
                            className="flex w-full items-center gap-4 px-4 py-3 text-left transition-colors hover:bg-muted/50"
                          >
                            <div className="min-w-0 flex-1 space-y-1">
                              <TypeMerchant r={r} />
                              <p className="truncate text-sm text-foreground/90">
                                {firstLine(r.text) || <span className="text-muted-foreground">#{r.post_id ?? "—"}</span>}
                              </p>
                            </div>
                            <div className="hidden shrink-0 text-right sm:block">
                              <div className="flex items-center justify-end gap-1 text-sm font-medium">
                                <HugeiconsIcon icon={Clock01Icon} className="h-3.5 w-3.5 text-muted-foreground" />
                                {relative(r.scheduled_at)}
                              </div>
                              <div className="text-xs text-muted-foreground">{istDateTime(r.scheduled_at)}</div>
                            </div>
                            <StatusPill status={r.status} className="shrink-0" />
                          </button>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
                <PagedNav page={d.page} pages={d.pages} onPageChange={setPage} />
              </>
            ) : (
              <Empty>Nothing scheduled yet. The agent fills each slot from your daily plan a few minutes before it fires.</Empty>
            )}
          </div>
        )}
      </Async>

      {/* row detail drawer — the actual post + its schedule facts */}
      <Sheet open={!!active} onOpenChange={(o) => !o && setActive(null)}>
        <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-md">
          {active && (
            <>
              <SheetHeader className="border-b">
                <SheetTitle className="flex items-center gap-2">
                  <HugeiconsIcon icon={Sent02Icon} className="h-4 w-4 text-primary" />
                  {postTypeLabel(active.post_type)}
                  {active.merchant && <span className="text-muted-foreground">· {merchantLabel(active.merchant)}</span>}
                </SheetTitle>
              </SheetHeader>
              <div className="space-y-4 p-4">
                {active.text ? (
                  <PostPreview text={active.text} />
                ) : (
                  <p className="text-sm text-muted-foreground">This queued row has no rendered post yet.</p>
                )}
                <div className="rounded-lg border">
                  <div className="divide-y divide-border px-3">
                    <DetailRow label="Fires"><span className="font-medium">{relative(active.scheduled_at)}</span> · {istDateTime(active.scheduled_at)}</DetailRow>
                    <DetailRow label="Status"><StatusPill status={active.status} /></DetailRow>
                    <DetailRow label="Earnings"><MoneyBadge affiliateStatus={active.affiliate_status} merchant={active.merchant} /></DetailRow>
                    <DetailRow label="Channel"><span className="font-mono text-xs">{active.channel || "—"}</span></DetailRow>
                    <DetailRow label="Attempts">{active.attempts}</DetailRow>
                    {active.note && (
                      <DetailRow label="Last error">
                        <span className="text-xs text-destructive">{active.note}</span>
                      </DetailRow>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
