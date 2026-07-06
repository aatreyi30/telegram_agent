import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Async, Empty } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { Badge } from "@/components/ui/primitives";
import { Card, CardContent } from "@/components/ui/card";
import { Pagination } from "@/components/ui/pagination";
import { api } from "@/services/api";

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

export function Drafts() {
  const [page, setPage] = useState(1);
  const q = useQuery({ queryKey: ["drafts", page], queryFn: () => api.get<any>(`/api/drafts?page=${page}&page_size=8`) });

  return (
    <div>
      <PageHeader
        title="Drafts"
        sub="Generated posts with real, clickable links + affiliate short links. Each shows why it follows the strategy."
      />
      <Async q={q} rows={3}>
        {(d) =>
          d.items.length ? (
            <div className="space-y-4">
              <div className="grid gap-4 lg:grid-cols-2">
                {d.items.map((r: any) => {
                  const aff = r.affiliate_status || "";
                  const rat = r.rationale || {};
                  const ep = rat.emoji_policy || r.emoji_policy || {};
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
                        {(rat.why_type || rat.target_window_ist?.why || ep.avoid?.length) && (
                          <div className="mt-3 space-y-1 text-xs text-muted-foreground">
                            {rat.why_type && <div><span className="font-medium text-foreground">Why this post:</span> {rat.why_type}</div>}
                            {rat.target_window_ist?.why && <div><span className="font-medium text-foreground">Best time:</span> {rat.target_window_ist.why}</div>}
                            {ep.avoid?.length ? (
                              <div><span className="font-medium text-foreground">Emoji policy:</span> lead {(ep.lead || []).join(" ")}; stripped {(ep.avoid || []).join(" ")}</div>
                            ) : null}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
              <Pagination page={d.page} pages={d.pages} total={d.total} onPage={setPage} />
            </div>
          ) : (
            <Empty>No drafts yet. Use “Generate from today’s deals” on the Overview.</Empty>
          )
        }
      </Async>
    </div>
  );
}
