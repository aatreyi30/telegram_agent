"use client";

import { useState } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  Alert01Icon,
  Calendar03Icon,
  CheckmarkCircle01Icon,
  Clock01Icon,
  Store01Icon,
} from "@hugeicons/core-free-icons";
import { Async, Empty } from "@/components/Async";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePlans, useWeekly } from "@/queries/queries";
import type { CampaignPlanDTO, PlanRisk } from "@/types/api";

type DailyPlan = Extract<CampaignPlanDTO, { plan_type: "daily" }>;
type EventPlan = Extract<CampaignPlanDTO, { plan_type: "event" }>;

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

function ConfidenceFooter({ confidence, evidence }: { confidence: number; evidence?: Record<string, unknown> | null }) {
  const bits = Object.entries(evidence || {}).map(([k, v]) => `${k}: ${v}`).join(" · ");
  return (
    <p className="border-t border-border pt-2 text-xs text-muted-foreground">
      Confidence {Math.round(confidence * 100)}%{bits ? ` · ${bits}` : ""}
    </p>
  );
}

function DailyPlanCard({ p }: { p: DailyPlan }) {
  const bp = p.blueprint;
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">{p.title}</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Stat label="Posts planned" value={String(bp.posts_planned)} />
          {p.expected_outcome && <Stat label="Est. daily reach" value={`~${p.expected_outcome.estimated_daily_views} views`} />}
        </div>

        {bp.posting_windows?.length > 0 && (
          <div>
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <HugeiconsIcon icon={Clock01Icon} size={14} /> Posting windows
            </p>
            <div className="flex flex-wrap gap-2">
              {bp.posting_windows.map((w, i) => (
                <div key={i} className="rounded-md border border-border px-2.5 py-1.5 text-xs">
                  <span className="font-medium">{w.part}</span> {w.hours} · {w.posts} posts
                </div>
              ))}
            </div>
          </div>
        )}

        {bp.deal_type_allocation?.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">Deal-type allocation</p>
            <Table>
              <TableHeader>
                <TableRow><TableHead>Deal type</TableHead><TableHead>Target posts</TableHead><TableHead>Views/day</TableHead></TableRow>
              </TableHeader>
              <TableBody>
                {bp.deal_type_allocation.map((a, i) => (
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

        {bp.merchant_allocation?.length > 0 && (
          <div>
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <HugeiconsIcon icon={Store01Icon} size={14} /> Merchant mix (last 45d)
            </p>
            <div className="space-y-1">
              {bp.merchant_allocation.map((m) => (
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

        {!!bp.emoji_strategy?.length && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Emoji strategy:</span>
            {bp.emoji_strategy.map((e) => <Badge key={e} variant="outline">{e}</Badge>)}
          </div>
        )}

        {bp.event_note && (
          <div className="flex items-start gap-2 rounded-md bg-primary/5 px-2.5 py-1.5 text-xs text-foreground">
            <HugeiconsIcon icon={Calendar03Icon} size={14} className="mt-0.5 shrink-0 text-primary" />
            {bp.event_note}
          </div>
        )}

        <RiskList risks={p.risks} />
        <ConfidenceFooter confidence={p.confidence} evidence={p.evidence} />
      </CardContent>
    </Card>
  );
}

function EventPlanCard({ p }: { p: EventPlan }) {
  const bp = p.blueprint;
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">{p.title}</CardTitle>
          <Badge variant={bp.date_confidence === "exact" ? "success" : "warning"}>{bp.date_confidence}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Event date" value={bp.event_date} />
          <Stat label="Days away" value={String(bp.days_away)} />
          <Stat label="Window" value={`${bp.window_days} days`} />
          <Stat label="Ramp" value={`${bp.ramp_multiplier}x`} />
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <div className="w-28 shrink-0 text-xs text-muted-foreground">Baseline</div>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-secondary">
              <div className="h-full rounded-full bg-muted-foreground/40" style={{ width: `${Math.round(100 / bp.ramp_multiplier)}%` }} />
            </div>
            <div className="w-20 shrink-0 text-right text-xs">{bp.baseline_posts_per_day}/day</div>
          </div>
          <div className="flex items-center gap-3">
            <div className="w-28 shrink-0 text-xs text-muted-foreground">During event</div>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-secondary">
              <div className="h-full rounded-full bg-primary" style={{ width: "100%" }} />
            </div>
            <div className="w-20 shrink-0 text-right text-xs font-medium">{bp.recommended_posts_per_day_during_event}/day</div>
          </div>
        </div>

        <div className="flex items-center gap-1.5 text-xs">
          <HugeiconsIcon icon={Store01Icon} size={14} className="text-muted-foreground" />
          Merchant focus: <span className="font-medium">{bp.merchant_focus}</span>
        </div>

        <div>
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">Prep checklist</p>
          <ul className="space-y-1">
            {bp.prep_checklist.map((c, i) => (
              <li key={i} className="flex items-start gap-2 text-xs">
                <HugeiconsIcon icon={CheckmarkCircle01Icon} size={14} className="mt-0.5 shrink-0 text-muted-foreground" />
                {c}
              </li>
            ))}
          </ul>
        </div>

        {bp.notes && <p className="text-xs text-muted-foreground">{bp.notes}</p>}
        <RiskList risks={p.risks} />
        <ConfidenceFooter confidence={p.confidence} evidence={p.evidence} />
      </CardContent>
    </Card>
  );
}

/** Renders each line of the AI weekly summary as a paragraph, promoting a
 * leading "Label: " to a bold inline heading when present — general-purpose,
 * not tied to a fixed set of expected section names. */
function AiSummaryBlock({ text }: { text: string }) {
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

function WeeklyTab() {
  const q = useWeekly();
  return (
    <Async q={q} rows={2}>
      {(d) =>
        !d.weekly_plan && !d.ai_summary ? (
          <Empty>No weekly report yet — run the agent or the pipeline.</Empty>
        ) : (
          <div className="space-y-4">
            {d.ai_summary && (
              <Card>
                <CardHeader><CardTitle className="text-base">This week — summary</CardTitle></CardHeader>
                <CardContent><AiSummaryBlock text={d.ai_summary} /></CardContent>
              </Card>
            )}
            {d.weekly_plan && (
              <Card>
                <CardHeader><CardTitle className="text-base">{d.weekly_plan.title}</CardTitle></CardHeader>
                <CardContent className="space-y-4 text-sm">
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <Stat label="Posts/day" value={String(d.weekly_plan.blueprint.posts_per_day)} />
                    <Stat label="Posts/week" value={String(d.weekly_plan.blueprint.posts_per_week)} />
                  </div>
                  {d.weekly_plan.blueprint.daily_themes?.length > 0 && (
                    <Table>
                      <TableHeader>
                        <TableRow><TableHead>Day</TableHead><TableHead>Date</TableHead><TableHead>Theme focus</TableHead><TableHead>Posts</TableHead></TableRow>
                      </TableHeader>
                      <TableBody>
                        {d.weekly_plan.blueprint.daily_themes.map((t, i) => (
                          <TableRow key={i}>
                            <TableCell className="font-medium">{t.day}</TableCell>
                            <TableCell className="text-muted-foreground">{t.date}</TableCell>
                            <TableCell>{t.theme_focus}</TableCell>
                            <TableCell>{t.posts_planned}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                  {!!d.weekly_plan.blueprint.rotation_for_diversity?.length && (
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-xs text-muted-foreground">Rotation for diversity:</span>
                      {d.weekly_plan.blueprint.rotation_for_diversity.map((t) => <Badge key={t} variant="outline">{t}</Badge>)}
                    </div>
                  )}
                  {!!d.weekly_plan.blueprint.upcoming_events?.length && (
                    <div className="flex flex-wrap gap-1.5">
                      <span className="text-xs text-muted-foreground">Upcoming events:</span>
                      {d.weekly_plan.blueprint.upcoming_events.map((e) => (
                        <Badge key={e.name} variant="outline">{e.name} ({e.days_away}d, {e.date_confidence})</Badge>
                      ))}
                    </div>
                  )}
                  <ConfidenceFooter confidence={d.weekly_plan.confidence} />
                </CardContent>
              </Card>
            )}
            <p className="text-xs text-muted-foreground">What changed &amp; the full recommendation list live in <b>Insights</b>.</p>
          </div>
        )
      }
    </Async>
  );
}

export default function PlanPage() {
  const [tab, setTab] = useState("daily");
  const q = usePlans();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Plan</h1>
        <p className="text-sm text-muted-foreground">
          What to post and when — built from your growth blueprint + the India sale calendar. Plans only; publishing is scheduled from the queue.
        </p>
      </div>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="daily">Daily</TabsTrigger>
          <TabsTrigger value="weekly">Weekly report</TabsTrigger>
          <TabsTrigger value="events">Events</TabsTrigger>
        </TabsList>

        <TabsContent value="daily">
          <div className="mt-4 space-y-4">
            <Async q={q}>
              {(plans) => {
                const daily = plans.filter((p): p is DailyPlan => p.plan_type === "daily");
                return daily.length ? daily.map((p, i) => <DailyPlanCard key={i} p={p} />)
                  : <Empty>No daily plan — run the agent or pipeline.</Empty>;
              }}
            </Async>
          </div>
        </TabsContent>

        <TabsContent value="weekly"><div className="mt-4"><WeeklyTab /></div></TabsContent>

        <TabsContent value="events">
          <div className="mt-4">
            <Async q={q}>
              {(plans) => {
                const events = plans.filter((p): p is EventPlan => p.plan_type === "event");
                return events.length ? <div className="space-y-4">{events.map((p, i) => <EventPlanCard key={i} p={p} />)}</div>
                  : <Empty>No sale event within the next 30 days — event campaigns appear here once one enters the planning window.</Empty>;
              }}
            </Async>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
