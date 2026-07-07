"use client";

import { Lightbulb, ListChecks, Smile, Target, TrendingUp } from "lucide-react";
import { Async } from "@/components/Async";
import { CalloutCard } from "@/components/CalloutCard";
import { BarsChart } from "@/components/charts";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useInsights } from "@/queries/queries";
import type { InsightsResponse } from "@/types/api";

// The blueprint's `blueprint` field is a loosely-typed Record<string, unknown> on
// the wire (its shape varies by mode/channel-type); `content_mix` is the one part
// of it this page renders, so it's typed narrowly here rather than in api.ts.
interface ContentMixRow {
  post_type: string;
  current_share: number | null;
  avg_views_per_day: number | null;
  action: "increase" | "maintain" | "decrease" | string;
}

const ACTION_BADGE: Record<string, "success" | "warning" | "default"> = {
  increase: "success",
  decrease: "warning",
  maintain: "default",
};

function EvidenceList({ evidence }: { evidence: Record<string, unknown> | null | undefined }) {
  const entries = Object.entries(evidence || {});
  if (!entries.length) return <span>No evidence attached.</span>;
  return (
    <dl className="space-y-1">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <dt className="shrink-0 font-medium text-foreground/80">{k}:</dt>
          <dd className="truncate">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function InsightsPage() {
  const q = useInsights();
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Insights</h1>
        <p className="text-sm text-muted-foreground">
          What the data says and why — with the calculation, time window, and sample behind each number.
        </p>
      </div>
      <Async q={q}>
        {(d: InsightsResponse) => {
          const contentMix = (d.blueprint?.blueprint?.content_mix ?? null) as ContentMixRow[] | null;
          return (
            <div className="space-y-8">
              {/* Recommendations */}
              <section>
                <h2 className="mb-3 text-lg font-semibold">Recommendations</h2>
                <div className="space-y-3">
                  {(d.recommendations || []).map((r, i) => (
                    <CalloutCard
                      key={i}
                      severity="info"
                      label={r.category || (r.priority != null ? `P${r.priority}` : undefined)}
                      title={r.recommendation}
                      evidence={<EvidenceList evidence={r.evidence} />}
                    >
                      {r.reasoning}
                      {r.expected_outcome && (
                        <div className="mt-1">Expected: {r.expected_outcome}</div>
                      )}
                    </CalloutCard>
                  ))}
                  {!(d.recommendations || []).length && (
                    <p className="text-sm text-muted-foreground">No recommendations yet.</p>
                  )}
                </div>
              </section>

              {/* Emoji policy */}
              {d.emoji_policy?.rules?.length > 0 && (
                <section>
                  <h2 className="mb-3 text-lg font-semibold">Emoji policy</h2>
                  <Card>
                    <CardContent className="p-4">
                      <p className="mb-3 text-sm text-muted-foreground">
                        Drafts strip the avoid-emojis automatically. Based on {d.emoji_policy.window}. Lift is
                        correlational, not causal — these emojis co-occur with your best/worst post types, not
                        proven to cause the difference.
                      </p>
                      <BarsChart
                        data={[...d.emoji_policy.rules]
                          .sort((a, b) => b.lift_pct - a.lift_pct)
                          .map((r) => ({ label: r.emoji, lift_pct: r.lift_pct }))}
                        dataKey="lift_pct"
                        unit="%"
                        height={Math.max(180, d.emoji_policy.rules.length * 28)}
                      />
                    </CardContent>
                  </Card>
                </section>
              )}

              {/* What changed & why */}
              <section>
                <h2 className="mb-3 text-lg font-semibold">What changed &amp; why</h2>
                {(d.reasoning || []).length ? (
                  <Card>
                    <CardContent className="p-0">
                      <Table>
                        <TableHeader>
                          <TableRow><TableHead>Metric</TableHead><TableHead>Change</TableHead><TableHead>What it means</TableHead></TableRow>
                        </TableHeader>
                        <TableBody>
                          {d.reasoning.map((i, k) => (
                            <TableRow key={k}>
                              <TableCell className="font-medium">{i.metric}</TableCell>
                              <TableCell>{i.direction} {i.change}{i.unit}</TableCell>
                              <TableCell>
                                {i.observation}
                                <div className="text-xs text-muted-foreground">{i.why}</div>
                                <div className="mt-0.5 text-xs text-muted-foreground">Period compared: {i.period}</div>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </CardContent>
                  </Card>
                ) : (
                  <p className="text-sm text-muted-foreground">No period-over-period shifts detected.</p>
                )}
              </section>

              {/* Performance */}
              <section>
                <h2 className="mb-3 text-lg font-semibold">Post-type performance</h2>
                <Card>
                  <CardContent className="p-0">
                    <Table>
                      <TableHeader>
                        <TableRow><TableHead>Rank</TableHead><TableHead>Post type</TableHead><TableHead>Posts</TableHead><TableHead>Share</TableHead><TableHead>Views/day</TableHead></TableRow>
                      </TableHeader>
                      <TableBody>
                        {(d.performance || []).map((p) => (
                          <TableRow key={p.post_type}>
                            <TableCell>#{p.rank}</TableCell>
                            <TableCell>{p.post_type}</TableCell>
                            <TableCell>{p.posts}</TableCell>
                            <TableCell>{p.share != null ? Math.round(p.share * 100) + "%" : "—"}</TableCell>
                            <TableCell>{p.avg_views_per_day != null ? Math.round(p.avg_views_per_day) : "—"}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              </section>

              {/* Content mix vs target */}
              {contentMix && contentMix.length > 0 && (
                <section>
                  <h2 className="mb-3 text-lg font-semibold">Your content mix vs. target</h2>
                  <Card>
                    <CardContent className="p-4">
                      <p className="mb-3 text-sm text-muted-foreground">
                        Current share of posts by type, and whether the growth blueprint says to lean in or pull back.
                      </p>
                      <div className="space-y-2">
                        {contentMix.map((m) => (
                          <div key={m.post_type} className="flex items-center gap-3">
                            <div className="w-32 shrink-0 truncate text-sm font-medium">{m.post_type}</div>
                            <div className="h-2 flex-1 overflow-hidden rounded-full bg-secondary">
                              <div
                                className="h-full rounded-full bg-primary"
                                style={{ width: `${Math.min(100, Math.round((m.current_share || 0) * 100))}%` }}
                              />
                            </div>
                            <div className="w-12 shrink-0 text-right text-sm text-muted-foreground">
                              {m.current_share != null ? Math.round(m.current_share * 100) + "%" : "—"}
                            </div>
                            <div className="w-20 shrink-0 text-right text-xs text-muted-foreground">
                              {m.avg_views_per_day != null ? Math.round(m.avg_views_per_day) + " views/day" : "—"}
                            </div>
                            <Badge variant={ACTION_BADGE[m.action] ?? "default"} className="w-20 shrink-0 justify-center">
                              {m.action}
                            </Badge>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                </section>
              )}

              {/* Learnings */}
              <section>
                <h2 className="mb-3 text-lg font-semibold">What the channel has learned</h2>
                <div className="space-y-3">
                  {(d.learnings || []).map((l, i) => (
                    <CalloutCard
                      key={i}
                      severity="success"
                      label={l.category}
                      title={l.statement}
                      evidence={
                        <EvidenceList
                          evidence={{
                            sample_size: l.sample_size,
                            confidence: l.confidence,
                            period: l.period,
                          }}
                        />
                      }
                    >
                      {l.how_calculated && <>How this is calculated: {l.how_calculated}</>}
                    </CalloutCard>
                  ))}
                  {!(d.learnings || []).length && (
                    <p className="text-sm text-muted-foreground">Nothing learned yet — check back after more data accrues.</p>
                  )}
                </div>
              </section>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
