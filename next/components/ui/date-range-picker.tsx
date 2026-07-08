"use client";

import { useState, useCallback } from "react";
import { CalendarIcon, ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover } from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import { cn } from "@/lib/utils";
import { format, addDays, subDays } from "date-fns";
import type { DateRange } from "react-day-picker";

const PRESETS = [
  { label: "7d", value: "7d" },
  { label: "30d", value: "30d" },
  { label: "90d", value: "90d" },
  { label: "All", value: "all" },
] as const;

// The Calendar (react-day-picker) works in LOCAL time — a clicked day is local
// midnight. So we must parse/serialize in local time too; using UTC (toISOString /
// "T00:00:00Z") shifts the calendar date back a day for any timezone east of UTC
// (e.g. IST), which made picking the 10th send the 9th to the backend.
function toDate(iso?: string): Date | undefined {
  return iso ? new Date(iso + "T00:00:00") : undefined;
}

function toISO(d: Date): string {
  return format(d, "yyyy-MM-dd");
}

function fmt(d?: string): string {
  if (!d) return "";
  return format(new Date(d + "T00:00:00"), "MMM d, yyyy");
}

interface DateFilterCommon {
  showArrows?: boolean;
  presetsOnly?: boolean;
  className?: string;
  min?: string;
  max?: string;
}

interface SingleProps extends DateFilterCommon {
  mode: "single";
  value?: string;
  onChange: (date: string) => void;
}

interface RangeProps extends DateFilterCommon {
  mode: "range";
  preset: string;
  onPresetChange: (preset: string) => void;
  from?: string;
  to?: string;
  onRangeChange: (from: string, to: string) => void;
}

type DateFilterProps = SingleProps | RangeProps;

function isSingle(p: DateFilterProps): p is SingleProps {
  return "value" in p;
}

function isRange(p: DateFilterProps): p is RangeProps {
  return "preset" in p;
}

function getPresetDays(preset: string): number | "all" {
  if (preset === "7d") return 7;
  if (preset === "30d") return 30;
  if (preset === "90d") return 90;
  return "all";
}

export function DateFilter(props: DateFilterProps) {
  const { showArrows = true, presetsOnly = false, className, min, max } = props;

  const [draftFrom, setDraftFrom] = useState<Date | undefined>();
  const [draftTo, setDraftTo] = useState<Date | undefined>();
  const [calendarOpen, setCalendarOpen] = useState(false);

  const handleArrowLeft = useCallback(() => {
    if (isSingle(props)) {
      const cur = toDate(props.value) ?? toDate(max);
      if (!cur) return;
      const prev = subDays(cur, 1);
      const m = toDate(min);
      if (m && prev < m) return;
      props.onChange(toISO(prev));
    } else if (isRange(props)) {
      if (props.preset === "custom" || props.preset === "all") return;
      const days = getPresetDays(props.preset);
      if (days === "all" || !days) return;
      const curFrom = toDate(props.from);
      const curTo = toDate(props.to) ?? toDate(max);
      if (!curFrom || !curTo) return;
      const shift = Math.max(1, Math.ceil(days / 2));
      const newFrom = subDays(curFrom, shift);
      const newTo = subDays(curTo, shift);
      const m = toDate(min);
      if (m && newFrom < m) return;
      props.onRangeChange(toISO(newFrom), toISO(newTo));
    }
  }, [props, min, max]);

  const handleArrowRight = useCallback(() => {
    if (isSingle(props)) {
      const cur = toDate(props.value) ?? toDate(max);
      if (!cur) return;
      const next = addDays(cur, 1);
      const m = toDate(max);
      if (m && next > m) return;
      props.onChange(toISO(next));
    } else if (isRange(props)) {
      if (props.preset === "custom" || props.preset === "all") return;
      const days = getPresetDays(props.preset);
      if (days === "all" || !days) return;
      const curFrom = toDate(props.from);
      const curTo = toDate(props.to) ?? toDate(max);
      if (!curFrom || !curTo) return;
      const shift = Math.max(1, Math.ceil(days / 2));
      const newFrom = addDays(curFrom, shift);
      const newTo = addDays(curTo, shift);
      const m = toDate(max);
      if (m && newTo > m) return;
      props.onRangeChange(toISO(newFrom), toISO(newTo));
    }
  }, [props, min, max]);

  const single = isSingle(props);
  const range = isRange(props);

  const rangeLabel = (() => {
    if (single) return props.value ? fmt(props.value) : null;
    if (range && props.preset === "custom" && props.from) {
      const f = fmt(props.from);
      const t = fmt(props.to);
      return f === t ? f : `${f} — ${t}`;
    }
    return null;
  })();

  const arrowDisabledLeft = (() => {
    if (!showArrows) return true;
    if (single) {
      const cur = toDate(props.value) ?? toDate(max);
      if (!cur) return true;
      const m = toDate(min);
      return !!(m && subDays(cur, 1) < m);
    }
    if (range) {
      if (props.preset === "custom" || props.preset === "all") return true;
      const curFrom = toDate(props.from);
      if (!curFrom) return true;
      const m = toDate(min);
      return !!(m && subDays(curFrom, 1) < m);
    }
    return true;
  })();

  const arrowDisabledRight = (() => {
    if (!showArrows) return true;
    if (single) {
      const cur = toDate(props.value) ?? toDate(max);
      if (!cur) return true;
      const m = toDate(max);
      return !!(m && addDays(cur, 1) > m);
    }
    if (range) {
      if (props.preset === "custom" || props.preset === "all") return true;
      const curTo = toDate(props.to) ?? toDate(max);
      if (!curTo) return true;
      const m = toDate(max);
      return !!(m && addDays(curTo, 1) > m);
    }
    return true;
  })();

  const popoverLabel = rangeLabel ?? (single ? "Pick a date" : "Custom range");

  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {showArrows && (
        <button
          type="button"
          onClick={handleArrowLeft}
          disabled={arrowDisabledLeft}
          className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-30"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
      )}

      {range && (
        <div className="flex rounded-lg border bg-card p-0.5">
          {PRESETS.map((p) => (
            <button
              key={p.value}
              type="button"
              onClick={() => props.onPresetChange(p.value)}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                props.preset === p.value
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
      )}

      {presetsOnly ? (
        range && rangeLabel && <span className="text-xs text-muted-foreground">{rangeLabel}</span>
      ) : (
        <Popover
          open={calendarOpen}
          onOpenChange={(o) => {
            setCalendarOpen(o);
            if (o && range && props.from) {
              setDraftFrom(toDate(props.from));
              setDraftTo(toDate(props.to));
            }
          }}
          trigger={
            <Button
              variant="outline"
              size="sm"
              className={cn("gap-2 min-w-[130px] justify-start", rangeLabel ? "text-foreground" : "text-muted-foreground")}
            >
              <CalendarIcon className="h-3.5 w-3.5 shrink-0" />
              {popoverLabel}
            </Button>
          }
        >
          <div className="space-y-2 p-3">
            {single && (
              <Calendar
                mode="single"
                selected={toDate(props.value)}
                onSelect={(d) => {
                  if (!d) return;
                  props.onChange(toISO(d));
                  setCalendarOpen(false);
                }}
                disabled={(date: Date) => {
                  const m = min ? new Date(min + "T00:00:00Z") : undefined;
                  const x = max ? new Date(max + "T00:00:00Z") : undefined;
                  return (!!m && date < m) || (!!x && date > x);
                }}
                autoFocus
              />
            )}
            {range && (
              <>
                <Calendar
                  mode="range"
                  selected={{ from: draftFrom, to: draftTo } as DateRange}
                  onSelect={(r) => {
                    if (!r) return;
                    setDraftFrom(r.from);
                    setDraftTo(r.to);
                  }}
                  disabled={(date: Date) => {
                    const m = min ? new Date(min + "T00:00:00Z") : undefined;
                    const x = max ? new Date(max + "T00:00:00Z") : undefined;
                    return (!!m && date < m) || (!!x && date > x);
                  }}
                  autoFocus
                />
                <div className="flex justify-end gap-2 border-t pt-2">
                  <Button size="sm" variant="ghost" onClick={() => setCalendarOpen(false)}>
                    Cancel
                  </Button>
                  <Button size="sm" disabled={!draftFrom} onClick={() => {
                    if (!draftFrom) return;
                    props.onRangeChange(toISO(draftFrom), toISO(draftTo ?? draftFrom));
                    setCalendarOpen(false);
                  }}>
                    Apply
                  </Button>
                </div>
              </>
            )}
          </div>
        </Popover>
      )}

      {showArrows && (
        <button
          type="button"
          onClick={handleArrowRight}
          disabled={arrowDisabledRight}
          className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-30"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      )}

      {single && max && (
        <Button
          variant="outline"
          size="sm"
          onClick={() => props.onChange("")}
        >
          Latest
        </Button>
      )}
    </div>
  );
}

/** @deprecated Use DateFilter instead */
export const DateRangePicker = DateFilter;
