import { useState } from "react";
import { Calendar as CalendarIcon } from "lucide-react";
import { Button } from "./button";
import { Popover } from "./popover";
import { Calendar, DateRange } from "./calendar";
import { cn } from "@/lib/utils";
import { DEFAULT_DATE_PRESETS } from "@/constants/dates";
import type { DatePreset } from "@/types/ui";

export type { DatePreset };

function fmt(d?: Date) {
  return d ? d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" }) : "";
}

/** Preset pills + a custom-range popover calendar — replaces the native
 * `<input type="date">` pair used across Analytics/DayView with one consistent,
 * themed component. Fully controlled: the page owns `value` and `activePreset`. */
export function DateRangePicker({
  value,
  onChange,
  presets = DEFAULT_DATE_PRESETS,
  minDate,
  maxDate,
  activePreset,
  onPresetChange,
}: {
  value: DateRange;
  onChange: (r: DateRange) => void;
  presets?: DatePreset[];
  minDate?: Date;
  maxDate?: Date;
  activePreset?: string;
  onPresetChange?: (label: string) => void;
}) {
  const [draft, setDraft] = useState<DateRange>(value);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex rounded-lg border bg-card p-0.5">
        {presets.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => onPresetChange?.(p.label)}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              activePreset === p.label
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            )}
          >
            {p.label}
          </button>
        ))}
      </div>
      <Popover
        trigger={({ onClick }) => (
          <Button
            variant={activePreset === "custom" ? "secondary" : "outline"}
            size="sm"
            className="gap-2"
            onClick={() => {
              setDraft(value);
              onClick();
            }}
          >
            <CalendarIcon className="h-3.5 w-3.5" />
            {value.from ? `${fmt(value.from)} – ${fmt(value.to ?? value.from)}` : "Custom range"}
          </Button>
        )}
      >
        {(close) => (
          <div className="space-y-2">
            <Calendar mode="range" selected={draft} onSelect={setDraft} minDate={minDate} maxDate={maxDate} />
            <div className="flex justify-end gap-2 border-t pt-2">
              <Button size="sm" variant="ghost" onClick={close}>Cancel</Button>
              <Button
                size="sm"
                disabled={!draft.from}
                onClick={() => {
                  if (draft.from) onChange(draft);
                  close();
                }}
              >
                Apply
              </Button>
            </div>
          </div>
        )}
      </Popover>
    </div>
  );
}
