"use client";

import { HugeiconsIcon } from "@hugeicons/react";
import {
  Alert01Icon,
  Calendar03Icon,
  Clock01Icon,
  Store01Icon,
} from "@hugeicons/core-free-icons";
import { Async, Empty } from "@/components/Async";
import { AiBadge } from "@/components/AiBadge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DateFilter } from "@/components/ui/date-range-picker";
import { useQueryParams } from "@/lib/use-search-params";
import { cn } from "@/lib/utils";
import { useDailyBrief, useWeeklyBrief } from "@/queries/queries";
import type {
  DailyBrief, DailyPlanToday, DailyTrajectory, PlanRisk, WeeklyBrief, WeeklyBriefDay, YesterdayBrief,
} from "@/types/api";

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

function ConfidenceFooter({ confidence }: { confidence: number }) {
  return (
    <p className="border-t border-border pt-2 text-xs text-muted-foreground">
      Confidence {Math.round(confidence * 100)}%
    </p>
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
      {entries.map(([k, v]) => <Badge key={k} variant="outline">{k}: {v}</Badge>)}
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
                {y!.best_category && <>Best category: <span className="font-medium text-foreground">{y!.best_category}</span></>}
                {y!.best_category && y!.worst_category && " · "}
                {y!.worst_category && <>Worst: <span className="font-medium text-foreground">{y!.worst_category}</span></>}
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

function TrajectoryBars({ trajectory }: { trajectory: DailyTrajectory }) {
  const max = Math.max(1, ...trajectory.days.map((d) => d.posts));
  return (
    <div className="space-y-2">
      <div className="flex h-16 items-end gap-1">
        {trajectory.days.map((d) => (
          <div key={d.date} className="flex flex-1 flex-col items-center gap-1" title={`${d.date}: ${d.posts} posts · ${Math.round(d.views_avg)} avg views`}>
            <div
              className="w-full rounded-t-sm bg-primary/70"
              style={{ height: `${Math.max(4, Math.round((d.posts / max) * 100))}%` }}
            />
            <span className="text-[9px] text-muted-foreground">{d.date.slice(5)}</span>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        recent ~{trajectory.recent_cadence}/day
        {trajectory.lifetime_baseline != null && <span className="text-muted-foreground"> vs lifetime {trajectory.lifetime_baseline}/day</span>}
      </p>
    </div>
  );
}

function TodayCard({ brief }: { brief: DailyBrief }) {
  const t: DailyPlanToday = brief.today;
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Today — {brief.date}</CardTitle></CardHeader>
      <CardContent className="space-y-5 text-sm">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-bold tracking-tight">{t.recommended_posts}</span>
            <span className="text-sm text-muted-foreground">posts recommended today</span>
          </div>
          {t.plan_clamped && (
            <p className="mt-1 text-xs text-muted-foreground" title="The AI's suggested count fell outside the safe range and was adjusted.">
              Adjusted for sanity from the AI's suggestion.
            </p>
          )}
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Badge variant="outline">{t.scheduled_count} scheduled today</Badge>
            {t.gap > 0 ? (
              <Badge variant="warning">{t.gap} more needed</Badge>
            ) : (
              <Badge variant="success">Fully scheduled</Badge>
            )}
          </div>
          {t.cadence_why && <p className="mt-1.5 text-sm text-foreground">{t.cadence_why}</p>}
        </div>

        <TrajectoryBars trajectory={brief.trajectory} />

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
                    <TableCell>{a.deal_type}</TableCell>
                    <TableCell>{a.target_posts}</TableCell>
                    <TableCell>{a.avg_views_per_day != null ? Math.round(a.avg_views_per_day) : "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {t.merchant_allocation?.length > 0 && (
          <div>
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <HugeiconsIcon icon={Store01Icon} size={14} /> Merchant mix
            </p>
            <div className="space-y-1">
              {t.merchant_allocation.map((m) => (
                <div key={m.merchant} className="flex items-center gap-2">
                  <div className="w-24 shrink-0 truncate text-xs">{m.merchant}</div>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-secondary">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round(m.recent_share * 100)}%` }} />
                  </div>
                  <div className="w-9 shrink-0 text-right text-xs text-muted-foreground">{Math.round(m.recent_share * 100)}%</div>
                </div>
              ))}
            </div>
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
                    <TableCell className="tabular-nums">{s.count ?? "—"}</TableCell>
                    <TableCell><Badge variant="outline">{s.type}</Badge></TableCell>
                    <TableCell className="text-muted-foreground">{s.theme}</TableCell>
                    <TableCell className="text-muted-foreground">{s.merchant || "mixed"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{s.why || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        <RiskList risks={t.risks} />
        <ConfidenceFooter confidence={t.confidence} />
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
            <TableCell className="text-muted-foreground">{d.date}</TableCell>
            <TableCell>{d.posts}</TableCell>
            <TableCell>{Math.round(d.views_avg).toLocaleString()}</TableCell>
            <TableCell className="text-emerald-600 dark:text-emerald-400">+{d.joined}</TableCell>
            <TableCell className="text-red-600 dark:text-red-400">-{d.left}</TableCell>
            <TableCell className={d.net < 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}>
              {d.net > 0 ? "+" : ""}{d.net}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function WeeklyView({ q }: { q: ReturnType<typeof useWeeklyBrief> }) {
  return (
    <Async q={q} rows={3}>
      {(w: WeeklyBrief) =>
        !w.available ? (
          <Empty>{w.reason || "No weekly plan available."}</Empty>
        ) : (
          <div className="space-y-4">
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
              </CardContent>
            </Card>

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
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Plan</h1>
          <p className="text-sm text-muted-foreground">
            What went well yesterday, and what to post today — grounded in your data.
          </p>
        </div>

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
      </div>

      {view === "daily" ? <DailyView q={dailyQ} /> : <WeeklyView q={weeklyQ} />}
    </div>
  );
}
