"use client";

import { useEffect, useRef, useState } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { Cancel01Icon, CheckmarkCircle02Icon, AlertCircleIcon, Sent02Icon } from "@hugeicons/core-free-icons";
import { useActivity } from "@/queries/queries";
import { cn } from "@/lib/utils";
import type { ActivityEvent } from "@/types/api";

const TOAST_MS = 6000;
// job_run events (queue_processor/jit_fill fire every minute) would spam this into
// noise — the toast stream only surfaces the events a human actually cares about.
const TOASTABLE = new Set<ActivityEvent["type"]>(["draft_created", "post_published", "post_blocked"]);

function iconFor(type: ActivityEvent["type"]) {
  if (type === "post_published") return CheckmarkCircle02Icon;
  if (type === "post_blocked") return AlertCircleIcon;
  return Sent02Icon;
}
function toneFor(type: ActivityEvent["type"]): string {
  if (type === "post_published") return "border-emerald-400/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
  if (type === "post_blocked") return "border-amber-400/40 bg-amber-500/10 text-amber-700 dark:text-amber-300";
  return "border-violet-400/40 bg-violet-500/10 text-violet-700 dark:text-violet-300";
}

interface LiveToast extends ActivityEvent { key: string; }

/** Live pop-up feed for what the agent is actually doing — a draft written, a post
 * sent, a post blocked — surfaced the moment the 15s poll sees it, not something
 * you have to go find in a table. Mounted once in the dashboard shell. */
export function ActivityToasts() {
  const { data } = useActivity(10);
  const [toasts, setToasts] = useState<LiveToast[]>([]);
  const seen = useRef<Set<string>>(new Set());
  const primed = useRef(false);

  useEffect(() => {
    if (!data?.events?.length) return;
    // first load: remember what's already there without toasting it — only genuinely
    // NEW events (arriving on later polls) should pop up.
    if (!primed.current) {
      for (const e of data.events) seen.current.add(`${e.type}:${e.at}:${e.ref_id}`);
      primed.current = true;
      return;
    }
    const fresh = data.events.filter((e) => {
      const key = `${e.type}:${e.at}:${e.ref_id}`;
      if (seen.current.has(key) || !TOASTABLE.has(e.type)) return false;
      seen.current.add(key);
      return true;
    });
    if (!fresh.length) return;
    const withKeys = fresh.map((e) => ({ ...e, key: `${e.type}:${e.at}:${e.ref_id}` }));
    setToasts((prev) => [...withKeys, ...prev].slice(0, 5));
    withKeys.forEach((t) => {
      setTimeout(() => setToasts((prev) => prev.filter((x) => x.key !== t.key)), TOAST_MS);
    });
  }, [data]);

  if (!toasts.length) return null;

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.key}
          className={cn(
            "pointer-events-auto flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm shadow-lg backdrop-blur animate-in slide-in-from-bottom-2 fade-in",
            toneFor(t.type),
          )}
        >
          <HugeiconsIcon icon={iconFor(t.type)} className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="flex-1 leading-snug">{t.label}</span>
          <button
            type="button"
            onClick={() => setToasts((prev) => prev.filter((x) => x.key !== t.key))}
            className="shrink-0 opacity-60 hover:opacity-100"
            aria-label="Dismiss"
          >
            <HugeiconsIcon icon={Cancel01Icon} className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
