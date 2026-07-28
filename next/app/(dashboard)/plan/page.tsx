"use client";

import { useEffect, useState, type ReactNode } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  Alert01Icon,
  Clock01Icon,
  InformationCircleIcon,
} from "@hugeicons/core-free-icons";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Async, Empty } from "@/components/Async";
import { AiBadge } from "@/components/AiBadge";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { Reveal } from "@/components/Reveal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DateFilter } from "@/components/ui/date-range-picker";
import { PageHeader } from "@/components/PageHeader";
import { useQueryParams } from "@/lib/use-search-params";
import { cn } from "@/lib/utils";
import { postTypeLabel, merchantLabel, categoryLabel, titleCase, statusLabel, isoSlash } from "@/lib/format";
import { useRegenerateDailyPlan, useRegenerateWeeklyPlan, useRevertDailyPlan } from "@/queries/mutations";
import { useDailyBrief, useLatestRetro, useWeeklyBrief } from "@/queries/queries";
import type {
  DailyBrief, DailyPlanToday, DailySlot, PlanRisk, RetroLatest, WeeklyBrief,
  WeeklyBriefDay, YesterdayBrief,
} from "@/types/api";

/** A slot's price intent, as the planner expressed it: a cap ("≤ ₹999"), a floor
 * ("≥ ₹500"), or a band. Blank when the slot set no price constraint — most don't,
 * and an em dash says that more honestly than a fabricated range. */
function priceIntent(s: DailySlot): string {
  const lo = s.min_price ?? null;
  const hi = s.max_price ?? null;
  if (lo != null && hi != null) return `₹${lo}–₹${hi}`;
  if (hi != null) return `≤ ₹${hi}`;
  if (lo != null) return `≥ ₹${lo}`;
  return "—";
}

/** Compact "Steer this plan" control shared by the daily TodayCard and the weekly
 * card: a directive textarea (prefilled with whatever's already persisted on the
 * plan) plus a Regenerate button. Disabled once the target day/week has elapsed —
 * steering the past has no effect. */
function SteerPanel({
  operatorDirective, canRegenerate, isPending, onRegenerate,
  canRevert, revertPending, onRevert,
}: {
  operatorDirective?: string | null;
  canRegenerate?: boolean;
  isPending: boolean;
  onRegenerate: (directive: string) => void;
  // Revert (undo the last steer) is daily-only and shown only when a pre-steer
  // snapshot exists — omitted by the weekly card.
  canRevert?: boolean;
  revertPending?: boolean;
  onRevert?: () => void;
}) {
  const [directive, setDirective] = useState(operatorDirective || "");
  useEffect(() => setDirective(operatorDirective || ""), [operatorDirective]);
  const disabled = canRegenerate === false;

  return (
    <div className="space-y-2 rounded-md border border-dashed border-border p-3">
      <p className="text-xs font-medium text-muted-foreground">Steer this plan</p>
      {operatorDirective && (
        <p className="text-xs text-muted-foreground">
          Steered by: <span className="italic text-foreground">&ldquo;{operatorDirective}&rdquo;</span>
        </p>
      )}
      <textarea
        className="min-h-16 w-full resize-y rounded-md border border-border bg-background px-2.5 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50"
        placeholder="Steer the AI — e.g. 'Push electronics harder today' or 'avoid the same merchant twice'…"
        value={directive}
        onChange={(e) => setDirective(e.target.value)}
        disabled={disabled}
      />
      <div className="flex items-center justify-end gap-2">
        {disabled && (
          <span className="text-xs text-muted-foreground" title="This day has elapsed">
            This day has elapsed — regenerating it has no effect.
          </span>
        )}
        {canRevert && onRevert && (
          <Button
            size="sm"
            variant="ghost"
            disabled={disabled || isPending || revertPending}
            title="Restore the plan from before the last steer"
            onClick={onRevert}
          >
            {revertPending ? "Reverting…" : "Revert steer"}
          </Button>
        )}
        <Button
          size="sm"
          variant="outline"
          disabled={disabled || isPending || revertPending}
          title={disabled ? "This day has elapsed" : undefined}
          onClick={() => onRegenerate(directive.trim())}
        >
          {isPending ? "Regenerating…" : "Regenerate"}
        </Button>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-muted/50 px-2.5 py-1.5 transition-colors duration-200 hover:bg-muted tabular-nums">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold"><AnimatedNumber value={value} /></p>
    </div>
  );
}

function RiskList({ risks }: { risks: PlanRisk[] | null }) {
  if (!risks?.length) return null;
  return (
    <div className="space-y-1.5">
      {risks.map((r, i) => (
        <div key={i} className="flex items-start gap-2 rounded-md bg-orange-50 px-2.5 py-1.5 text-xs text-orange-900 dark:bg-orange-950 dark:text-orange-200">
          <HugeiconsIcon icon={Alert01Icon} size={14} className="mt-0.5 shrink-0" />
          <span>{r.detail}</span>
        </div>
      ))}
    </div>
  );
}

/** Strips the handful of markdown tokens the AI sometimes emits (headers,
 * bold) that the deterministic fallback / prompt never asks for but the
 * model occasionally reaches for anyway — this is a plain-text panel, not a
 * markdown renderer, so tokens are removed rather than styled. */
function stripInlineMarkdown(s: string): string {
  return s.replace(/\*\*(.+?)\*\*/g, "$1").replace(/`(.+?)`/g, "$1");
}

/** Renders an AI narrative: a leading "Label: " promotes to a bold inline
 * heading, a "### " line becomes a section heading, and consecutive "1. "-style
 * lines group into an ordered list — general-purpose, not tied to fixed
 * section names (the model's exact wording/structure varies run to run). */
function DigestBlock({ text }: { text: string }) {
  const lines = text.split(/\n+/).filter(Boolean).map((l) => l.trim());
  const blocks: ReactNode[] = [];
  let listBuf: string[] = [];
  const flushList = (key: string) => {
    if (!listBuf.length) return;
    blocks.push(
      <ol key={key} className="ml-4 list-decimal space-y-1">
        {listBuf.map((item, j) => <li key={j}>{stripInlineMarkdown(item)}</li>)}
      </ol>,
    );
    listBuf = [];
  };

  lines.forEach((line, i) => {
    const heading = /^#{1,6}\s+(.+)$/.exec(line);
    const numbered = /^\d+[.)]\s+(.+)$/.exec(line);
    const labeled = /^([A-Za-z][A-Za-z' ]{2,39}):\s*(.+)$/.exec(line);

    if (numbered) {
      listBuf.push(numbered[1]);
      return;
    }
    flushList(`list-${i}`);

    if (heading) {
      blocks.push(<p key={i} className="font-semibold text-foreground">{stripInlineMarkdown(heading[1])}</p>);
    } else if (labeled) {
      blocks.push(
        <p key={i}><span className="font-semibold text-foreground">{labeled[1]}:</span> {stripInlineMarkdown(labeled[2])}</p>,
      );
    } else {
      blocks.push(<p key={i}>{stripInlineMarkdown(line)}</p>);
    }
  });
  flushList("list-end");

  return <div className="space-y-2 text-sm leading-relaxed">{blocks}</div>;
}

function TypeMixBadges({ mix }: { mix: Record<string, number> | null }) {
  const entries = Object.entries(mix || {});
  if (!entries.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs font-medium text-muted-foreground">Type mix:</span>
      {entries.map(([k, v]) => <Badge key={k} variant="outline">{postTypeLabel(k)}: {v}</Badge>)}
    </div>
  );
}

function YesterdayCard({ y, prevDate }: { y: YesterdayBrief | null; prevDate: string }) {
  const noActivity = !y || y.source === "none";
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Yesterday — {isoSlash(prevDate)}</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        {noActivity ? (
          <p className="text-sm text-muted-foreground">No activity recorded.</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Posts" value={String(y!.posts_count)} />
              <Stat label="Avg views" value={Math.round(y!.views_avg).toLocaleString()} />
              <Stat label="Engagement rate" value={`${y!.engagement_rate}%`} />
              {y!.subs_net != null && (
                <Stat label="Subscribers" value={`${y!.subs_net >= 0 ? "+" : ""}${y!.subs_net} subs`} />
              )}
            </div>
            {y!.top_post_id != null && (
              <p className="text-xs text-muted-foreground">Top post: #{y!.top_post_id}</p>
            )}
            <TypeMixBadges mix={y!.type_mix} />
            {y!.best_category && (
              <p className="text-xs text-muted-foreground">
                Best merchant: <span className="font-medium text-foreground">{merchantLabel(y!.best_category)}</span>
              </p>
            )}
            {y!.source === "live" && (
              <p className="text-xs text-muted-foreground">(computed live from posts — no stored report)</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function TodayCard({ brief }: { brief: DailyBrief }) {
  const t: DailyPlanToday = brief.today;
  const regenerate = useRegenerateDailyPlan();
  const revert = useRevertDailyPlan();
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Today — {isoSlash(brief.date)}</CardTitle></CardHeader>
      <CardContent className="space-y-5 text-sm">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold tracking-tight tabular-nums">{t.recommended_posts}</span>
            <span className="text-sm text-muted-foreground">posts recommended today</span>
          </div>
          {t.plan_clamped && (
            <p className="mt-1 text-xs text-muted-foreground" title="The AI's suggested count fell outside the safe range and was adjusted.">
              Adjusted for sanity from the AI's suggestion.
            </p>
          )}
          {(() => {
            // Under just-in-time filling the plan's SLOTS are the schedule — each is
            // rendered into a real post only ~3 min before it fires. So "planned" is the
            // sum of slot counts, NOT how many rows have materialised yet (that would
            // always read as a deficit all day). Only a genuine plan shortfall is a gap.
            const planned = (t.slots || []).reduce((a, s) => a + (s.count ?? 1), 0);
            const short = Math.max(t.recommended_posts - planned, 0);
            const over = Math.max(planned - t.recommended_posts, 0);
            return (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <Badge variant="outline">{planned} planned across {t.slots?.length || 0} slots</Badge>
                {short > 0 ? (
                  <Badge variant="warning">{short} short of target</Badge>
                ) : over > 0 ? (
                  <Badge variant="warning">{over} over target</Badge>
                ) : (
                  <Badge variant="success">On target</Badge>
                )}
                {t.scheduled_count > 0 && (
                  <span className="text-xs text-muted-foreground">{t.scheduled_count} filled so far today</span>
                )}
              </div>
            );
          })()}
        </div>

        {brief.digest ? (
          <div className="ai-surface ai-sheen relative overflow-hidden space-y-1.5 rounded-xl border bg-gradient-to-b from-violet-500/[0.04] to-transparent p-3.5">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground">Narrative</span>
              <AiBadge />
            </div>
            <DigestBlock text={brief.digest} />
            {brief.factcheck_status === "failed" ? (
              <p className="text-xs font-medium text-red-600 dark:text-red-400">
                ⚠ This plan failed verification — the numbers aren't grounded in the data. Regenerate it.
              </p>
            ) : brief.factcheck_status === "warn" ? (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                Some cited numbers could not be verified against the data.
              </p>
            ) : null}
          </div>
        ) : !brief.ai_available ? (
          <p className="text-xs text-muted-foreground">AI narrative unavailable — relying on the numbers below.</p>
        ) : null}

        {(t.emphasis || t.watch) && (
          <div className="space-y-1">
            {t.emphasis && <p><span className="font-medium">Emphasis:</span> {t.emphasis}</p>}
            {t.watch && <p><span className="font-medium">Watch:</span> {t.watch}</p>}
          </div>
        )}

        {t.posting_windows?.length > 0 && (
          <div>
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <HugeiconsIcon icon={Clock01Icon} size={14} /> Posting windows
            </p>
            <div className="flex flex-wrap gap-2">
              {t.posting_windows.map((w, i) => (
                <div key={i} className="rounded-md border border-border px-2.5 py-1.5 text-xs">
                  <span className="font-medium">{w.part}</span> {w.hours} · {w.posts} posts
                </div>
              ))}
            </div>
          </div>
        )}

        {t.deal_type_allocation?.length > 0 && (() => {
          const totalPosts = t.deal_type_allocation.reduce((sum, a) => sum + (a.target_posts || 0), 0);
          return (
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">Deal-type allocation</p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Deal type</TableHead>
                  <TableHead>
                    <span className="inline-flex items-center gap-1">
                      Target posts
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <HugeiconsIcon icon={InformationCircleIcon} className="h-3.5 w-3.5 cursor-help text-muted-foreground" />
                        </TooltipTrigger>
                        <TooltipContent className="max-w-xs">
                          Today&apos;s {totalPosts} recommended posts, split across deal types by each type&apos;s measured performance — with a 30% floor so neither type ever drops out.
                        </TooltipContent>
                      </Tooltip>
                    </span>
                  </TableHead>
                  <TableHead>
                    <span className="inline-flex items-center gap-1">
                      Avg views/post
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <HugeiconsIcon icon={InformationCircleIcon} className="h-3.5 w-3.5 cursor-help text-muted-foreground" />
                        </TooltipTrigger>
                        <TooltipContent className="max-w-xs">
                          The real average of actual view counts across every post of this type — measured from your history, not an estimate.
                        </TooltipContent>
                      </Tooltip>
                    </span>
                  </TableHead>
                  <TableHead>Why</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {t.deal_type_allocation.map((a, i) => (
                  <TableRow key={i}>
                    <TableCell>{postTypeLabel(a.deal_type)}</TableCell>
                    <TableCell className="tabular-nums">{a.target_posts}</TableCell>
                    <TableCell className="tabular-nums">{a.avg_views_per_post != null ? Math.round(a.avg_views_per_post) : "—"}</TableCell>
                    <TableCell className="max-w-md text-xs leading-snug text-muted-foreground">{a.reasoning || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          );
        })()}

        {t.slots?.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">
              Today's posting schedule — the brief for the content engine
            </p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8">#</TableHead><TableHead>Time (IST)</TableHead><TableHead>Posts</TableHead>
                  <TableHead>Type</TableHead><TableHead>Theme</TableHead>
                  <TableHead>Merchant</TableHead>
                  <TableHead>Why</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {t.slots.map((s, i) => (
                  <TableRow key={i}>
                    <TableCell className="tabular-nums text-muted-foreground">{i + 1}</TableCell>
                    <TableCell className="font-medium tabular-nums">{s.time_ist || s.window_ist || "—"}</TableCell>
                    <TableCell className="tabular-nums">{s.time_ist ? 1 : (s.count ?? 1)}</TableCell>
                    <TableCell><Badge variant="secondary" className="font-medium">{postTypeLabel(s.type)}</Badge></TableCell>
                    <TableCell className="text-muted-foreground">{categoryLabel(s.theme) || "—"}</TableCell>
                    <TableCell className="text-muted-foreground">{merchantLabel(s.merchant)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{s.why || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        <RiskList risks={t.risks} />

        <SteerPanel
          operatorDirective={brief.operator_directive}
          canRegenerate={brief.can_regenerate}
          isPending={regenerate.isPending}
          onRegenerate={(directive) =>
            regenerate.mutate({ date: brief.date, directive: directive || undefined })
          }
          canRevert={brief.can_revert}
          revertPending={revert.isPending}
          onRevert={() => revert.mutate({ date: brief.date })}
        />

      </CardContent>
    </Card>
  );
}

function UpcomingEventCallout({ event }: { event: NonNullable<DailyBrief["upcoming_event"]> }) {
  return (
    <div className="flex items-center gap-2 rounded-md bg-primary/5 px-3 py-2 text-sm text-foreground">
      <span>🛍 {event.name} in {event.days_away} days ({event.date_confidence}) — consider ramping.</span>
    </div>
  );
}

function DailyView({ q }: { q: ReturnType<typeof useDailyBrief> }) {
  return (
    <Async q={q} rows={3}>
      {(brief) =>
        !brief.available ? (
          <Empty>{brief.reason || "No plan available."}</Empty>
        ) : (
          <div className="space-y-4">
            <Reveal index={0}><YesterdayCard y={brief.yesterday} prevDate={brief.prev_date} /></Reveal>
            <Reveal index={1}><TodayCard brief={brief} /></Reveal>
            {brief.upcoming_event && <Reveal index={2}><UpcomingEventCallout event={brief.upcoming_event} /></Reveal>}
          </div>
        )
      }
    </Async>
  );
}

function WeekDaysTable({ days }: { days: WeeklyBriefDay[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Day</TableHead><TableHead>Date</TableHead><TableHead>Posts</TableHead><TableHead>Avg views</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {/* Joined/Left/Net columns removed: Telegram exposes only the LIVE subscriber
            count (no history), so per-day follower deltas can't be captured reliably. */}
        {days.map((d) => (
          <TableRow key={d.date}>
            <TableCell className="font-medium">{d.weekday}</TableCell>
            <TableCell className="text-muted-foreground tabular-nums">{isoSlash(d.date)}</TableCell>
            <TableCell className="tabular-nums">{d.posts}</TableCell>
            <TableCell className="tabular-nums">
              {Math.round(d.views_avg).toLocaleString()}
              {d.views_maturing && (
                <span className="ml-1 text-xs text-muted-foreground" title="Posts from the last few days are still accumulating views — this average will keep rising and isn't a dip.">
                  · still rising
                </span>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Prediction accuracy, rule-based adjustments, and the engagement/churn
 * readout behind them — the point of Phase 2.4's predict->outcome->retro
 * loop made visible. Renders nothing while there's no retro yet (never seeds
 * fake data) rather than showing an empty shell. */
function RetroCard({ q }: { q: ReturnType<typeof useLatestRetro> }) {
  return (
    <Async q={q} rows={2}>
      {(r: RetroLatest) => {
        if (!r.available) return null;
        const { prediction, plan_adherence, engagement, churn_vs_frequency, adjustments, top_over, top_under } = r.metrics;
        // The retro reviews prediction accuracy + plan adherence. Until the predict->
        // outcome->score loop has produced data, all of that is empty — so hide the card
        // rather than show a stale, all-"—" panel (it reappears once there's real data).
        if (prediction.n_posts === 0 && plan_adherence.planned === 0 && plan_adherence.published === 0)
          return null;
        const pct = (v: number | null) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${Math.round(v * 100)}%`);
        return (
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="text-base">Weekly retro — week of {isoSlash(r.week_start)}</CardTitle>
                <AiBadge />
              </div>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Stat label="Avg forecast error" value={prediction.mape_views_24h != null ? `${Math.round(prediction.mape_views_24h * 100)}%` : "—"} />
                <Stat label="Runs high / low" value={prediction.bias == null ? "—" : `${prediction.bias >= 0 ? "over " : "under "}${pct(Math.abs(prediction.bias))}`} />
                <Stat label="Posts scored" value={String(prediction.n_posts)} />
                <Stat label="Published / planned" value={`${plan_adherence.published}/${plan_adherence.planned}`} />
              </div>

              <div className="flex flex-wrap items-center gap-1.5">
                {engagement.best_hour_bucket && <Badge variant="outline">Best time: {titleCase(engagement.best_hour_bucket)}</Badge>}
                {engagement.best_type_by_engagement && <Badge variant="outline">Best format: {postTypeLabel(engagement.best_type_by_engagement)}</Badge>}
                {engagement.median_forward_rate != null && (
                  <Badge variant="outline">Typical forward rate: {(engagement.median_forward_rate * 100).toFixed(1)}%</Badge>
                )}
                {plan_adherence.blocked_stale > 0 && <Badge variant="warning">{plan_adherence.blocked_stale} {statusLabel("blocked_stale").toLowerCase()}s</Badge>}
              </div>

              {(churn_vs_frequency.high_leave_days_posts_per_day != null || churn_vs_frequency.low_leave_days_posts_per_day != null) && (
                <p className="text-xs text-muted-foreground">
                  Posts/day on high-churn days:{" "}
                  <span className="font-medium text-foreground">{churn_vs_frequency.high_leave_days_posts_per_day != null ? Math.round(churn_vs_frequency.high_leave_days_posts_per_day) : "—"}</span>
                  {" "}vs low-churn days:{" "}
                  <span className="font-medium text-foreground">{churn_vs_frequency.low_leave_days_posts_per_day != null ? Math.round(churn_vs_frequency.low_leave_days_posts_per_day) : "—"}</span>
                </p>
              )}

              {adjustments?.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-medium text-muted-foreground">Adjustments for next week</p>
                  <ul className="space-y-1.5">
                    {adjustments.map((a, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs">
                        <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
                        <span>{a}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {(top_over.length > 0 || top_under.length > 0) && (
                <div className="grid gap-3 sm:grid-cols-2">
                  {top_over.length > 0 && (
                    <div>
                      <p className="mb-1 text-xs font-medium text-muted-foreground">Biggest over-performers</p>
                      <ul className="space-y-1 text-xs text-muted-foreground">
                        {top_over.map((m) => (
                          <li key={m.post_id}>
                            Post #{m.post_id} · forecast {m.pred?.toLocaleString() ?? "—"} → got {m.actual?.toLocaleString() ?? "—"}
                            {m.merchant ? ` · ${merchantLabel(m.merchant)}` : ""}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {top_under.length > 0 && (
                    <div>
                      <p className="mb-1 text-xs font-medium text-muted-foreground">Biggest under-performers</p>
                      <ul className="space-y-1 text-xs text-muted-foreground">
                        {top_under.map((m) => (
                          <li key={m.post_id}>
                            Post #{m.post_id} · forecast {m.pred?.toLocaleString() ?? "—"} → got {m.actual?.toLocaleString() ?? "—"}
                            {m.merchant ? ` · ${merchantLabel(m.merchant)}` : ""}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {r.narrative && <DigestBlock text={r.narrative} />}
            </CardContent>
          </Card>
        );
      }}
    </Async>
  );
}

function WeekCard({ w }: { w: WeeklyBrief }) {
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Last 7 days — {isoSlash(w.week_start)} to {isoSlash(w.week_end)}</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Posts" value={String(w.totals.posts)} />
          <Stat label="Total views" value={w.totals.views_total.toLocaleString()} />
          <Stat label="Posts/day so far (actual)" value={String(Math.round(w.totals.avg_posts_per_day))} />
          <Stat label="Recommended/day" value={String(w.recommended_posts_per_day)} />
        </div>

        {/* The weekly PLAN's strategy — the recommendations that steer the daily plans. */}
        {(w.direction || w.loot_deal_ratio || (w.merchant_priorities?.length ?? 0) > 0) && (
          <div className="space-y-2 rounded-md border border-border bg-muted/30 p-3">
            <p className="text-xs font-medium text-muted-foreground">This week&apos;s direction</p>
            {w.direction && <p className="text-sm font-medium text-foreground">{w.direction}</p>}
            {w.loot_deal_ratio && (() => {
              const { loot, deal } = w.loot_deal_ratio!;
              const lootPct = Math.round((loot / ((loot || 0) + (deal || 0) || 1)) * 100);
              return (
                <div className="flex items-center gap-1.5 text-xs">
                  <span className="text-muted-foreground">Target mix:</span>
                  <Badge variant="outline">Single {100 - lootPct}%</Badge>
                  <Badge variant="outline">Loot {lootPct}%</Badge>
                </div>
              );
            })()}
            {(w.merchant_priorities?.length ?? 0) > 0 && (
              <div>
                <p className="mb-1 text-xs text-muted-foreground">Feature these merchants:</p>
                <ul className="space-y-1">
                  {w.merchant_priorities!.map((m, i) => (
                    <li key={i} className="text-xs">
                      <span className="font-medium text-foreground">{merchantLabel(m.merchant)}</span>
                      {m.why && <span className="text-muted-foreground"> — {m.why}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {w.days?.length > 0 && <WeekDaysTable days={w.days} />}

      </CardContent>
    </Card>
  );
}

function WeeklyView({ q }: { q: ReturnType<typeof useWeeklyBrief> }) {
  const retroQ = useLatestRetro();
  const regenerate = useRegenerateWeeklyPlan();
  return (
    <Async q={q} rows={3}>
      {(w: WeeklyBrief) =>
        !w.available ? (
          <Empty>{w.reason || "No weekly plan available."}</Empty>
        ) : (
          <div className="space-y-4">
            <Reveal index={0}><RetroCard q={retroQ} /></Reveal>
            <Reveal index={1}><WeekCard w={w} /></Reveal>

            {w.digest ? (
              <Reveal index={2} as="div">
              <Card className="ai-surface ai-sheen overflow-hidden bg-gradient-to-b from-violet-500/[0.04] to-transparent">
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <CardTitle className="text-base">Weekly narrative</CardTitle>
                    <AiBadge />
                  </div>
                </CardHeader>
                <CardContent>
                  <DigestBlock text={w.digest} />
                  {/* When the honest grounded fallback is already shown, it explains
                      itself — don't also show the contradictory "failed, regenerate"
                      warning (regenerating usually just fails again). */}
                  {w.digest?.includes("Grounded summary") ? null
                    : w.factcheck_status === "failed" ? (
                    <p className="mt-1.5 text-xs font-medium text-red-600 dark:text-red-400">
                      ⚠ This plan failed verification — the numbers aren't grounded in the data. Regenerate it.
                    </p>
                  ) : w.factcheck_status === "warn" ? (
                    <p className="mt-1.5 text-xs text-amber-600 dark:text-amber-400">
                      Some cited numbers could not be verified against the data.
                    </p>
                  ) : null}
                </CardContent>
              </Card>
              </Reveal>
            ) : !w.ai_available ? (
              <p className="text-xs text-muted-foreground">AI narrative unavailable — relying on the numbers above.</p>
            ) : null}

            <Reveal index={3} as="div">
            <Card>
              <CardContent className="pt-6">
                <SteerPanel
                  operatorDirective={w.operator_directive}
                  canRegenerate={w.can_regenerate}
                  isPending={regenerate.isPending}
                  onRegenerate={(directive) =>
                    regenerate.mutate({ end: w.week_end, directive: directive || undefined })
                  }
                />
              </CardContent>
            </Card>
            </Reveal>
          </div>
        )
      }
    </Async>
  );
}

export default function PlanPage() {
  const { get, set } = useQueryParams();
  const view = get("view", "daily") === "weekly" ? "weekly" : "daily";
  const date = get("date", "");

  const dailyQ = useDailyBrief(date || undefined);
  const weeklyQ = useWeeklyBrief(date || undefined);

  const min = dailyQ.data?.min_date;
  const max = dailyQ.data?.max_date;

  const handleViewChange = (v: "daily" | "weekly") => set({ view: v === "daily" ? null : v });
  const handleDateChange = (val: string) => set({ date: val || null });

  return (
    <div className="space-y-4">
      <PageHeader
        title="Plan"
        subtitle="What went well yesterday, and what to post today — grounded in your data."
        actions={
          <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg border bg-card p-0.5">
            {(["daily", "weekly"] as const).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => handleViewChange(v)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors",
                  view === v ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {v}
              </button>
            ))}
          </div>
          <DateFilter mode="single" value={date} onChange={handleDateChange} min={min} max={max} showArrows />
          </div>
        }
      />

      {view === "daily" ? <DailyView q={dailyQ} /> : <WeeklyView q={weeklyQ} />}
    </div>
  );
}
