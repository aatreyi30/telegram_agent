"use client";

import { useState } from "react";
import { Async, Empty } from "@/components/Async";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useDrafts } from "@/queries/queries";
import type { DraftsResponse, EmojiPolicy, StrategyRationale } from "@/types/api";

const URL_RE = /(https?:\/\/[^\s]+)/g;

function Linkified({ text }: { text: string }) {
  const parts = text.split(URL_RE);
  return (
    <pre className="whitespace-pre-wrap break-words rounded-lg border bg-background p-3 text-sm leading-relaxed">
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
              <div className="grid gap-4 lg:grid-cols-2">
                {d.items.map((r) => {
                  const aff = r.affiliate_status || "";
                  const rat: Partial<StrategyRationale> = r.rationale ?? {};
                  const ep: Partial<EmojiPolicy> = rat.emoji_policy || r.emoji_policy || {};
                  return (
                    <Card key={r.id}>
                      <CardContent className="p-4">
                        <div className="mb-2 flex flex-wrap items-center gap-2">
                          <Badge>#{r.id}</Badge>
                          <Badge variant="primary">{r.post_type}</Badge>
                          <Badge variant={r.status === "published" ? "success" : "default"}>{r.status}</Badge>
                          {aff.endsWith("_applied") ? (
                            <Badge variant="success">affiliate links</Badge>
                          ) : aff ? (
                            <Badge variant="warning">clean url</Badge>
                          ) : null}
                        </div>
                        <Linkified text={r.text} />
                        {(rat.why_type || rat.target_window_ist?.why || ep.avoid?.length || rat.why_this_deal?.why) && (
                          <div className="mt-3 space-y-1 text-xs text-muted-foreground">
                            {rat.why_type && <div><span className="font-medium text-foreground">Why this post:</span> {rat.why_type}</div>}
                            {rat.target_window_ist?.why && <div><span className="font-medium text-foreground">Best time:</span> {rat.target_window_ist.why}</div>}
                            {ep.avoid?.length ? (
                              <div><span className="font-medium text-foreground">Emoji policy:</span> lead {(ep.lead || []).join(" ")}; stripped {(ep.avoid || []).join(" ")}</div>
                            ) : null}
                            {rat.why_this_deal?.why && <div><span className="font-medium text-foreground">Why this deal:</span> {rat.why_this_deal.why}</div>}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
              <div className="flex items-center justify-center gap-3">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={d.page <= 1}
                >
                  Previous
                </Button>
                <span className="text-sm text-muted-foreground">
                  Page {d.page} of {d.pages} ({d.total} total)
                </span>
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
          ) : (
            <Empty>No drafts yet. Use “Generate from today’s deals” on the Overview.</Empty>
          )
        }
      </Async>
    </div>
  );
}
