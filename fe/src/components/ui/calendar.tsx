import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { DateRange } from "@/types/ui";

export type { DateRange };

const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

function daysInMonth(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate();
}
function startWeekday(year: number, month: number) {
  const d = new Date(year, month, 1).getDay(); // 0=Sun
  return (d + 6) % 7; // 0=Mon
}
function sameDay(a?: Date, b?: Date) {
  return !!a && !!b && a.toDateString() === b.toDateString();
}
function stripTime(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** Pure-Tailwind month-grid calendar — no external date-picker dependency,
 * consistent with this codebase's hand-rolled ui/ primitives. Supports single-date
 * or range selection. */
export function Calendar({
  mode = "single",
  selected,
  onSelect,
  minDate,
  maxDate,
  month,
  onMonthChange,
}: {
  mode?: "single" | "range";
  selected?: Date | DateRange;
  onSelect?: (value: any) => void;
  minDate?: Date;
  maxDate?: Date;
  month?: Date;
  onMonthChange?: (d: Date) => void;
}) {
  const [internalMonth, setInternalMonth] = useState(
    month ?? (mode === "range" ? (selected as DateRange)?.from : (selected as Date)) ?? new Date()
  );
  const view = month ?? internalMonth;
  const setView = (d: Date) => (onMonthChange ? onMonthChange(d) : setInternalMonth(d));

  const year = view.getFullYear();
  const m = view.getMonth();
  const total = daysInMonth(year, m);
  const offset = startWeekday(year, m);
  const cells: (Date | null)[] = [
    ...Array(offset).fill(null),
    ...Array.from({ length: total }, (_, i) => new Date(year, m, i + 1)),
  ];

  const isDisabled = (d: Date) => (!!minDate && d < stripTime(minDate)) || (!!maxDate && d > stripTime(maxDate));

  const inRange = (d: Date) => {
    if (mode !== "range" || !selected) return false;
    const r = selected as DateRange;
    if (!r.from) return false;
    const to = r.to ?? r.from;
    return d >= stripTime(r.from) && d <= stripTime(to);
  };

  function pick(d: Date) {
    if (isDisabled(d)) return;
    if (mode === "single") {
      onSelect?.(d);
      return;
    }
    const r = (selected as DateRange) || {};
    if (!r.from || (r.from && r.to)) onSelect?.({ from: d, to: undefined });
    else onSelect?.(d < r.from ? { from: d, to: r.from } : { from: r.from, to: d });
  }

  return (
    <div className="w-64 rounded-lg border bg-popover p-3 text-popover-foreground shadow-md">
      <div className="mb-2 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setView(new Date(year, m - 1, 1))}
          className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label="Previous month"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <div className="text-sm font-medium">
          {view.toLocaleDateString("en-US", { month: "long", year: "numeric" })}
        </div>
        <button
          type="button"
          onClick={() => setView(new Date(year, m + 1, 1))}
          className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label="Next month"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
      <div className="grid grid-cols-7 gap-0.5 text-center text-[11px] text-muted-foreground">
        {WEEKDAYS.map((w) => (
          <div key={w} className="py-1">{w}</div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-0.5">
        {cells.map((d, i) => {
          if (!d) return <div key={i} />;
          const disabled = isDisabled(d);
          const active = mode === "single" ? sameDay(d, selected as Date) : inRange(d);
          const endpoint =
            mode === "range" &&
            (sameDay(d, (selected as DateRange)?.from) || sameDay(d, (selected as DateRange)?.to));
          const today = sameDay(d, new Date());
          return (
            <button
              key={i}
              type="button"
              disabled={disabled}
              onClick={() => pick(d)}
              className={cn(
                "aspect-square rounded-md text-xs transition-colors",
                disabled && "cursor-not-allowed text-muted-foreground/40",
                !disabled && !active && "hover:bg-muted",
                active && !endpoint && "bg-primary/15 text-primary",
                endpoint && "bg-primary font-semibold text-primary-foreground",
                today && !active && "border border-primary/50"
              )}
            >
              {d.getDate()}
            </button>
          );
        })}
      </div>
    </div>
  );
}
