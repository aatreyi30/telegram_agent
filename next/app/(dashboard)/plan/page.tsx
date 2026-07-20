"use client";

import { useEffect, useState } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  Alert01Icon,
  Calendar03Icon,
  Clock01Icon,
} from "@hugeicons/core-free-icons";
import { Async, Empty } from "@/components/Async";
import { AiBadge } from "@/components/AiBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DateFilter } from "@/components/ui/date-range-picker";
import { PageHeader } from "@/components/PageHeader";
import { useQueryParams } from "@/lib/use-search-params";
import { cn } from "@/lib/utils";
import { postTypeLabel, merchantLabel, categoryLabel, titleCase, statusLabel } from "@/lib/format";
import { useRegenerateDailyPlan, useRegenerateWeeklyPlan } from "@/queries/mutations";
import { useDailyBrief, useLatestRetro, useWeeklyBrief } from "@/queries/queries";
import type {
  DailyBrief, DailyPlanToday, PlanRisk, RetroLatest, WeeklyBrief,
  WeeklyBriefDay, YesterdayBrief,
} from "@/types/api";

/** Compact "Steer this plan" control shared by the daily TodayCard and the weekly
 * card: a directive textarea (prefilled with whatever's already persisted on the
 * plan) plus a Regenerate button. Disabled once the target day/week has elapsed —
 * steering the past has no effect. */
function SteerPanel({
  operatorDirective, canRegenerate, isPending, onRegenerate,
}: {
  operatorDirective?: string | null;
  canRegenerate?: boolean;
  isPending: boolean;
  onRegenerate: (directive: string) => void;
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
        <Button
          size="sm"
          variant="outline"
          disabled={disabled || isPending}
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
    <div className="rounded-md bg-muted/50 px-2.5 py-1.5">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold">{value}</p>
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

/** Renders an AI narrative, promoting a leading "Label: " to a bold inline
 * heading when present — general-purpose, not tied to fixed section names. */
function DigestBlock({ text }: { text: string }) {
  const lines = text.split(/\n+/).filter(Boolean);
  return (
    <div className="space-y-2 text-sm leading-relaxed">
      {lines.map((line, i) => {
        const m = /^([A-Za-z][A-Za-z' ]{2,39}):\s*(.+)$/.exec(line.trim());
        return m ? (
          <p key={i}><span className="font-semibold text-foreground">{m[1]}:</span> {m[2]}</p>
        ) : (
          <p key={i}>{line}</p>
        );
      })}
    </div>
  );
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
      <CardHeader><CardTitle className="text-base">Yesterday — {prevDate}</CardTitle></CardHeader>
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
            {(y!.best_category || y!.worst_category) && (
              <p className="text-xs text-muted-foreground">
                {y!.best_category && <>Best category: <span className="font-medium text-foreground">{categoryLabel(y!.best_category)}</span></>}
                {y!.best_category && y!.worst_category && " · "}
                {y!.worst_category && <>Worst: <span className="font-medium text-foreground">{categoryLabel(y!.worst_category)}</span></>}
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
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Today — {brief.date}</CardTitle></CardHeader>
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
            return (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <Badge variant="outline">{planned} planned across {t.slots?.length || 0} slots</Badge>
                {short > 0 ? (
                  <Badge variant="warning">{short} short of target</Badge>
                ) : (
                  <Badge variant="success">On target</Badge>
                )}
                {t.scheduled_count > 0 && (
                  <span className="text-xs text-muted-foreground">{t.scheduled_count} filled so far today</span>
                )}
              </div>
            );
          })()}
          {t.cadence_why && <p className="mt-1.5 text-sm text-foreground">{t.cadence_why}</p>}
        </div>

        {brief.digest ? (
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground">Narrative</span>
              <AiBadge />
            </div>
            <DigestBlock text={brief.digest} />
            {brief.factcheck_status === "warn" && (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                Some cited numbers could not be verified against the data.
              </p>
            )}
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

        {t.deal_type_allocation?.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">Deal-type allocation</p>
            <Table>
              <TableHeader>
                <TableRow><TableHead>Deal type</TableHead><TableHead>Target posts</TableHead><TableHead>Views/day</TableHead></TableRow>
              </TableHeader>
              <TableBody>
                {t.deal_type_allocation.map((a, i) => (
                  <TableRow key={i}>
                    <TableCell>{postTypeLabel(a.deal_type)}</TableCell>
                    <TableCell>{a.target_posts}</TableCell>
                    <TableCell>{a.avg_views_per_day != null ? Math.round(a.avg_views_per_day) : "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {t.slots?.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">
              Today's posting schedule — the brief for the content engine
            </p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Window (IST)</TableHead><TableHead>Posts</TableHead>
                  <TableHead>Type</TableHead><TableHead>Theme</TableHead>
                  <TableHead>Merchant</TableHead><TableHead>Why</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {t.slots.map((s, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-medium tabular-nums">{s.window_ist}</TableCell>
                    <TableCell className="tabular-nums">{s.count ?? 1}</TableCell>
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
            <YesterdayCard y={brief.yesterday} prevDate={brief.prev_date} />
            <TodayCard brief={brief} />
            {brief.upcoming_event && <UpcomingEventCallout event={brief.upcoming_event} />}
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
          <TableHead>Joined</TableHead><TableHead>Left</TableHead><TableHead>Net</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {days.map((d) => (
          <TableRow key={d.date}>
            <TableCell className="font-medium">{d.weekday}</TableCell>
            <TableCell className="text-muted-foreground tabular-nums">{d.date}</TableCell>
            <TableCell className="tabular-nums">{d.posts}</TableCell>
            <TableCell className="tabular-nums">{Math.round(d.views_avg).toLocaleString()}</TableCell>
            <TableCell className="text-emerald-600 tabular-nums dark:text-emerald-400">+{d.joined}</TableCell>
            <TableCell className="text-red-600 tabular-nums dark:text-red-400">-{d.left}</TableCell>
            <TableCell className={cn("tabular-nums", d.net < 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400")}>
              {d.net > 0 ? "+" : ""}{d.net}
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
        const pct = (v: number | null) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${Math.round(v * 100)}%`);
        return (
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="text-base">Weekly retro — week of {r.week_start}</CardTitle>
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
                  <span className="font-medium text-foreground">{churn_vs_frequency.high_leave_days_posts_per_day ?? "—"}</span>
                  {" "}vs low-churn days:{" "}
                  <span className="font-medium text-foreground">{churn_vs_frequency.low_leave_days_posts_per_day ?? "—"}</span>
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
  const regenerate = useRegenerateWeeklyPlan();
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">This week — {w.week_start} to {w.week_end}</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Posts" value={String(w.totals.posts)} />
          <Stat label="Total views" value={w.totals.views_total.toLocaleString()} />
          <Stat label="Avg posts/day" value={w.totals.avg_posts_per_day.toFixed(1)} />
          <Stat label="Recommended/day" value={String(w.recommended_posts_per_day)} />
        </div>

        {w.days?.length > 0 && <WeekDaysTable days={w.days} />}

        {w.themes?.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">Daily themes</p>
            <Table>
              <TableHeader>
                <TableRow><TableHead>Day</TableHead><TableHead>Date</TableHead><TableHead>Theme focus</TableHead><TableHead>Posts</TableHead></TableRow>
              </TableHeader>
              <TableBody>
                {w.themes.map((t, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-medium">{t.day}</TableCell>
                    <TableCell className="text-muted-foreground">{t.date}</TableCell>
                    <TableCell>{t.theme_focus}</TableCell>
                    <TableCell>{t.posts_planned}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {!!w.upcoming_events?.length && (
          <div className="flex flex-wrap items-center gap-1.5">
            <HugeiconsIcon icon={Calendar03Icon} size={14} className="text-muted-foreground" />
            <span className="text-xs text-muted-foreground">Upcoming events:</span>
            {w.upcoming_events.map((e) => (
              <Badge key={e.name} variant="outline">{e.name} ({e.days_away}d, {e.date_confidence})</Badge>
            ))}
          </div>
        )}

        <SteerPanel
          operatorDirective={w.operator_directive}
          canRegenerate={w.can_regenerate}
          isPending={regenerate.isPending}
          onRegenerate={(directive) =>
            regenerate.mutate({ end: w.week_start, directive: directive || undefined })
          }
        />
      </CardContent>
    </Card>
  );
}

function WeeklyView({ q }: { q: ReturnType<typeof useWeeklyBrief> }) {
  const retroQ = useLatestRetro();
  return (
    <Async q={q} rows={3}>
      {(w: WeeklyBrief) =>
        !w.available ? (
          <Empty>{w.reason || "No weekly plan available."}</Empty>
        ) : (
          <div className="space-y-4">
            <RetroCard q={retroQ} />
            <WeekCard w={w} />

            {w.digest ? (
              <Card>
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <CardTitle className="text-base">Weekly narrative</CardTitle>
                    <AiBadge />
                  </div>
                </CardHeader>
                <CardContent><DigestBlock text={w.digest} /></CardContent>
              </Card>
            ) : !w.ai_available ? (
              <p className="text-xs text-muted-foreground">AI narrative unavailable — relying on the numbers above.</p>
            ) : null}
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
