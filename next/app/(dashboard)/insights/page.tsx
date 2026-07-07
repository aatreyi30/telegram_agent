"use client";

import { useMemo } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  Analytics01Icon,
  ArrowDown01Icon,
  ArrowUp01Icon,
  BarChartIcon,
  Idea01Icon,
  Target02Icon,
} from "@hugeicons/core-free-icons";
import { Async } from "@/components/Async";
import { cn } from "@/lib/utils";
import { CalloutCard } from "@/components/CalloutCard";
import { BarsChart } from "@/components/charts";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DateFilter } from "@/components/ui/date-range-picker";
import { useInsights, useDataRange } from "@/queries/queries";
import { useQueryParams } from "@/lib/use-search-params";
import type { ContentMixRow, InsightsResponse } from "@/types/api";

const ACTION_BADGE: Record<string, "success" | "warning" | "default"> = {
  increase: "success",
  decrease: "warning",
  maintain: "default",
};

const ACTION_COPY: Record<string, string> = {
  increase: "Lean in — above-median performer, share is being nudged up.",
  decrease: "Pull back — below-median performer, share is being nudged down.",
  maintain: "On target — roughly in line with the channel median.",
};

function minusDays(iso: string, days: number): string {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

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

function RecommendationRow({ rank, r }: { rank: number; r: InsightsResponse["recommendations"][number] }) {
  return (
    <details className="group border-b border-border last:border-0">
      <summary className="flex cursor-pointer list-none items-start gap-3 px-4 py-3 hover:bg-muted/40">
        <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-muted text-[10px] font-semibold text-muted-foreground">
          {rank}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {r.category && <Badge variant="outline" className="shrink-0 text-[10px] uppercase tracking-wide">{r.category}</Badge>}
            <span className="text-sm font-medium leading-snug text-foreground">{r.recommendation}</span>
          </div>
          {r.expected_outcome && (
            <div className="mt-1 truncate text-xs text-muted-foreground">Expected: {r.expected_outcome}</div>
          )}
        </div>
        <span className="mt-0.5 shrink-0 text-xs text-muted-foreground">{Math.round(r.confidence * 100)}%</span>
      </summary>
      <div className="space-y-2 px-4 pb-3 pl-11 text-xs text-muted-foreground">
        <p>{r.reasoning}</p>
        <EvidenceList evidence={r.evidence} />
      </div>
    </details>
  );
}

export default function InsightsPage() {
  const range = useDataRange();
  const min = range.data?.min ?? undefined;
  const max = range.data?.max ?? undefined;

  const { get, set } = useQueryParams();
  const preset = get("preset", "30d");
  const startParam = get("start", "");
  const endParam = get("end", "");

  const { start, end } = useMemo(() => {
    if (preset === "custom") return { start: startParam || undefined, end: endParam || undefined };
    if (!max || !min) return { start: undefined, end: undefined };
    if (preset === "all") return { start: min, end: max };
    const days: Record<string, number> = { "7d": 7, "30d": 30, "90d": 90 };
    const d = days[preset] ?? 30;
    return { start: minusDays(max, d), end: max };
  }, [preset, min, max, startParam, endParam]);

  const q = useInsights(start, end, { enabled: !!range.data });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Insights</h1>
          <p className="text-sm text-muted-foreground">
            What the data says and why — with the calculation, time window, and sample behind each number.
          </p>
        </div>
        <DateFilter
          mode="range"
          preset={preset}
          onPresetChange={(p) => set({ preset: p, start: null, end: null })}
          from={start}
          to={end}
          onRangeChange={(f, t) => set({ preset: "custom", start: f, end: t })}
          min={min}
          max={max}
        />
      </div>
      <Async q={q}>
        {(d: InsightsResponse) => {
          const contentMix = d.content_mix as ContentMixRow[] | null;
          return (
            <div className="space-y-8">
              {/* Recommendations */}
              <section>
                <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
                  <HugeiconsIcon icon={Idea01Icon} size={18} className="text-primary" /> Recommendations
                </h2>
                {(d.recommendations || []).length ? (
                  <Card className="overflow-hidden py-0">
                    <CardContent className="p-0">
                      {d.recommendations.map((r, i) => (
                        <RecommendationRow key={i} rank={i + 1} r={r} />
                      ))}
                    </CardContent>
                  </Card>
                ) : (
                  <p className="text-sm text-muted-foreground">No recommendations yet.</p>
                )}
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
                <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
                  <HugeiconsIcon icon={Analytics01Icon} size={18} className="text-primary" /> What changed &amp; why
                </h2>
                {(d.reasoning || []).length ? (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {d.reasoning.map((i, k) => {
                      const up = i.direction === "up";
                      return (
                        <Card key={k}>
                          <CardContent className="p-4">
                            <div className="flex items-start justify-between gap-3">
                              <div className="text-sm font-medium text-foreground">{i.metric}</div>
                              <span
                                className={cn(
                                  "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold",
                                  up ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100"
                                     : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100",
                                )}
                              >
                                <HugeiconsIcon icon={up ? ArrowUp01Icon : ArrowDown01Icon} size={12} />
                                {i.change != null ? `${Math.abs(i.change)}${i.unit ?? ""}` : "—"}
                              </span>
                            </div>
                            <p className="mt-2 text-sm text-muted-foreground">{i.observation}</p>
                            <p className="mt-1 text-xs text-muted-foreground">{i.why}</p>
                            <p className="mt-2 text-xs text-muted-foreground/70">
                              Period compared: {i.period} · confidence {Math.round(i.confidence * 100)}%
                            </p>
                          </CardContent>
                        </Card>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No period-over-period shifts detected in this range.</p>
                )}
              </section>

              {/* Performance */}
              <section>
                <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
                  <HugeiconsIcon icon={BarChartIcon} size={18} className="text-primary" /> Post-type performance
                </h2>
                <p className="mb-3 text-sm text-muted-foreground">
                  Raw stats per post type for the selected range — how many posts, what share of volume, and
                  age-normalized views per day.
                </p>
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
                        {!(d.performance || []).length && (
                          <TableRow><TableCell colSpan={5} className="text-center text-muted-foreground">No posts in this range.</TableCell></TableRow>
                        )}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              </section>

              {/* Content mix vs target */}
              {contentMix && contentMix.length > 0 && (
                <section>
                  <h2 className="mb-1 flex items-center gap-2 text-lg font-semibold">
                    <HugeiconsIcon icon={Target02Icon} size={18} className="text-primary" /> Content mix — current vs. target
                  </h2>
                  <p className="mb-3 text-sm text-muted-foreground">
                    <strong>Target</strong> is a bounded nudge off your current share: post types earning
                    meaningfully more views/day than the channel median get a higher target (capped at 30%);
                    below-median types get a lower one. It is a direction to lean toward, not a hard quota.
                  </p>
                  <Card>
                    <CardContent className="divide-y divide-border p-0">
                      {contentMix.map((m) => {
                        const current = Math.round((m.current_share || 0) * 100);
                        const target = m.target_share != null ? Math.round(m.target_share * 100) : current;
                        return (
                          <div key={m.post_type} className="space-y-1.5 p-4">
                            <div className="flex items-center justify-between gap-3">
                              <div className="truncate text-sm font-medium">{m.post_type}</div>
                              <Badge variant={ACTION_BADGE[m.action] ?? "default"}>{m.action}</Badge>
                            </div>
                            <div className="relative h-2.5 overflow-hidden rounded-full bg-secondary">
                              <div className="h-full rounded-full bg-primary/40" style={{ width: `${Math.min(100, current)}%` }} />
                              <div
                                className="absolute top-0 h-full w-0.5 bg-foreground"
                                style={{ left: `${Math.min(100, target)}%` }}
                                title={`Target: ${target}%`}
                              />
                            </div>
                            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
                              <span>Current {current}% · Target {target}%</span>
                              <span>{m.avg_views_per_day != null ? `${Math.round(m.avg_views_per_day)} views/day` : "—"}</span>
                            </div>
                            <p className="text-xs text-muted-foreground/80">{ACTION_COPY[m.action] ?? ""}</p>
                          </div>
                        );
                      })}
                    </CardContent>
                  </Card>
                </section>
              )}
            </div>
          );
        }}
      </Async>
    </div>
  );
}
