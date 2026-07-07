"use client";

import { useState } from "react";
import { Async, Empty } from "@/components/Async";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { PagedNav } from "@/components/PagedNav";
import { useDrafts } from "@/queries/queries";
import type { DraftsResponse, EmojiPolicy, StrategyRationale } from "@/types/api";

const URL_RE = /(https?:\/\/[^\s]+)/g;

function Linkified({ text }: { text: string }) {
  const parts = text.split(URL_RE);
  return (
    <pre className="whitespace-pre-wrap break-words rounded-md bg-muted/40 p-3 text-sm leading-relaxed">
      {parts.map((p, i) =>
        URL_RE.test(p) ? (
          <a key={i} href={p} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2">
            {p}
          </a>
        ) : (
          <span key={i}>{p}</span>
        )
      )}
    </pre>
  );
}

function DraftCard({ r }: { r: DraftsResponse["items"][number] }) {
  const aff = r.affiliate_status || "";
  const rat: Partial<StrategyRationale> = r.rationale ?? {};
  const ep: Partial<EmojiPolicy> = rat.emoji_policy || r.emoji_policy || {};
  const hasRationale = rat.why_type || rat.target_window_ist?.why || ep.avoid?.length || rat.why_this_deal?.why;

  return (
    <Card className="overflow-hidden py-0">
      <CardHeader className="gap-0 border-b border-border bg-muted/20 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="font-mono text-[10px]">#{r.id}</Badge>
          <Badge variant="primary">{r.post_type}</Badge>
          <Badge variant={r.status === "published" ? "success" : "default"}>{r.status}</Badge>
          {aff.endsWith("_applied") ? (
            <Badge variant="success">affiliate links</Badge>
          ) : aff ? (
            <Badge variant="warning">clean url</Badge>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-3 p-4">
        <Linkified text={r.text} />
        {hasRationale && (
          <div className="space-y-1 text-xs text-muted-foreground">
            {rat.why_type && <div><span className="font-medium text-foreground">Why this post:</span> {rat.why_type}</div>}
            {rat.target_window_ist?.why && <div><span className="font-medium text-foreground">Best time:</span> {rat.target_window_ist.why}</div>}
            {!!ep.avoid?.length && (
              <div><span className="font-medium text-foreground">Emoji policy:</span> lead {(ep.lead || []).join(" ")}; stripped {(ep.avoid || []).join(" ")}</div>
            )}
            {rat.why_this_deal?.why && <div><span className="font-medium text-foreground">Why this deal:</span> {rat.why_this_deal.why}</div>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function DraftsPage() {
  const [page, setPage] = useState(1);
  const q = useDrafts(page);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Drafts</h1>
        <p className="text-sm text-muted-foreground">
          Generated posts with real, clickable links + affiliate short links. Each shows why it follows the strategy.
        </p>
      </div>
      <Async q={q} rows={3}>
        {(d: DraftsResponse) =>
          d.items.length ? (
            <div className="space-y-4">
              <p className="text-xs text-muted-foreground">{d.total} draft{d.total === 1 ? "" : "s"} total</p>
              <div className="grid gap-4 lg:grid-cols-2">
                {d.items.map((r) => <DraftCard key={r.id} r={r} />)}
              </div>
              <PagedNav page={d.page} pages={d.pages} onPageChange={setPage} />
            </div>
          ) : (
            <Empty>No drafts yet. Use "Generate from today's deals" on the Overview.</Empty>
          )
        }
      </Async>
    </div>
  );
}
