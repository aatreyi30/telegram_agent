"use client";

import { Async, Empty } from "@/components/Async";
import { AiBadge } from "@/components/AiBadge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDigest } from "@/queries/queries";

const FACTCHECK_BADGE: Record<string, "success" | "warning" | "destructive" | "default"> = {
  passed: "success",
  failed: "destructive",
  skipped: "warning",
};

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-muted/50 px-2.5 py-1.5">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold">{value}</p>
    </div>
  );
}

export default function DigestPage() {
  const q = useDigest();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Daily Digest</h1>
        <p className="text-sm text-muted-foreground">
          The AI's read on yesterday and today's focus — grounded in your report data and fact-checked before it reaches you.
        </p>
      </div>
      <Async q={q}>
        {(d) =>
          !d.available ? (
            <Empty>No AI digest yet — it appears after the first daily report + planning run.</Empty>
          ) : (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <div className="flex flex-wrap items-center gap-2">
                    <CardTitle className="text-base">How yesterday went, and today&apos;s focus</CardTitle>
                    <AiBadge />
                    {d.factcheck_status && (
                      <Badge variant={FACTCHECK_BADGE[d.factcheck_status] ?? "default"} className="ml-auto">
                        fact-check: {d.factcheck_status}
                      </Badge>
                    )}
                  </div>
                </CardHeader>
                <CardContent>
                  <p className="whitespace-pre-line text-sm leading-relaxed">{d.digest}</p>
                </CardContent>
              </Card>

              {!!d.plan?.post_slots?.length && (
                <Card>
                  <CardHeader><CardTitle className="text-base">Today&apos;s plan</CardTitle></CardHeader>
                  <CardContent className="p-0">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Window (IST)</TableHead>
                          <TableHead>Type</TableHead>
                          <TableHead>Theme</TableHead>
                          <TableHead>Why</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {d.plan.post_slots.map((s, i) => (
                          <TableRow key={i}>
                            <TableCell className="font-medium">{s.window_ist}</TableCell>
                            <TableCell>{s.type}</TableCell>
                            <TableCell className="text-muted-foreground">{s.theme}</TableCell>
                            <TableCell className="text-xs text-muted-foreground">{s.why ?? "—"}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                  {(d.plan.emphasis || d.plan.watch) && (
                    <CardContent className="space-y-1 border-t border-border pt-3 text-sm">
                      {d.plan.emphasis && <p><span className="font-medium">Emphasis:</span> {d.plan.emphasis}</p>}
                      {d.plan.watch && <p><span className="font-medium">Watch:</span> {d.plan.watch}</p>}
                    </CardContent>
                  )}
                </Card>
              )}

              {d.reconciliation && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Yesterday: planned vs. actual</CardTitle>
                    <CardDescription>{d.reconciliation.caveat}</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4 text-sm">
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      <Stat label="Planned" value={String(d.reconciliation.adherence.planned)} />
                      <Stat label="Published" value={String(d.reconciliation.adherence.published)} />
                      <Stat label="Matched" value={String(d.reconciliation.adherence.matched)} />
                      <Stat label="Missed windows" value={String(d.reconciliation.adherence.missed_windows.length)} />
                    </div>

                    {!!d.reconciliation.adherence.missed_windows.length && (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-xs font-medium text-muted-foreground">Missed:</span>
                        {d.reconciliation.adherence.missed_windows.map((w, i) => (
                          <Badge key={`${w}-${i}`} variant="outline">{w}</Badge>
                        ))}
                      </div>
                    )}

                    {!!d.reconciliation.attribution.items.length && (
                      <div>
                        <p className="mb-1.5 text-xs font-medium text-muted-foreground">
                          Expected vs. actual ({d.reconciliation.attribution.correlational ? "correlational" : "n/a"})
                        </p>
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Metric</TableHead>
                              <TableHead className="text-right">Expected</TableHead>
                              <TableHead className="text-right">Actual</TableHead>
                              <TableHead className="text-right">Gap</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {d.reconciliation.attribution.items.map((it, i) => (
                              <TableRow key={i}>
                                <TableCell>{it.metric}</TableCell>
                                <TableCell className="text-right">{it.expected}</TableCell>
                                <TableCell className="text-right">{it.actual ?? "—"}</TableCell>
                                <TableCell className="text-right">{it.gap ?? "—"}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}
            </div>
          )
        }
      </Async>
    </div>
  );
}
