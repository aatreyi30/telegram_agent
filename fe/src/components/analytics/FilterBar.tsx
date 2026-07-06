import { Calendar, ChevronDown, Filter, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

interface FilterOption { key: string; label: string; }

const PRESETS: { key: string; label: string; days: number | null }[] = [
  { key: "7d", label: "7d", days: 7 },
  { key: "30d", label: "30d", days: 30 },
  { key: "90d", label: "90d", days: 90 },
  { key: "6mo", label: "6 mo", days: 182 },
  { key: "12mo", label: "12 mo", days: 365 },
  { key: "all", label: "All", days: null },
];

export function FilterBar({ preset, onPresetChange, customStart, customEnd, onCustomStart, onCustomEnd,
  min, max, onCustomMode, isCustom, categories, selectedCategory, onCategoryChange, className }:
  {
    preset: string; onPresetChange: (k: string) => void;
    customStart: string; customEnd: string; onCustomStart: (v: string) => void; onCustomEnd: (v: string) => void;
    min?: string; max?: string; onCustomMode?: () => void; isCustom?: boolean;
    categories?: FilterOption[]; selectedCategory?: string; onCategoryChange?: (v: string) => void;
    className?: string;
  }) {
  return (
    <div className={cn("sticky top-14 z-20 -mx-4 md:-mx-6 mb-4", className)}>
      <Card className="border-t-0 rounded-none md:rounded-b-xl shadow-sm">
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <Button key={p.key} size="sm" variant={preset === p.key ? "default" : "outline"}
                onClick={() => { onPresetChange(p.key); }}>
                {p.label}
              </Button>
            ))}
            <Button size="sm" variant={isCustom ? "default" : "outline"} onClick={() => {
              if (onCustomMode) onCustomMode(); else onPresetChange("custom");
            }}>
              <Calendar size={13} className="mr-1" /> Custom
            </Button>
          </div>
          {isCustom && (
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-1">
                <Label className="text-[10px]">From</Label>
                <Input type="date" className="w-36 h-8 text-xs" min={min} max={max}
                  value={customStart || min || ""} onChange={(e) => { onCustomStart(e.target.value); onPresetChange("custom"); }} />
              </div>
              <div className="space-y-1">
                <Label className="text-[10px]">To</Label>
                <Input type="date" className="w-36 h-8 text-xs" min={min} max={max}
                  value={customEnd || max || ""} onChange={(e) => { onCustomEnd(e.target.value); onPresetChange("custom"); }} />
              </div>
            </div>
          )}
          {categories && categories.length > 0 && (
            <div className="flex items-center gap-2 ml-auto">
              <Filter size={13} className="text-muted-foreground shrink-0" />
              <select
                className="h-8 rounded-lg border bg-background px-2.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                value={selectedCategory || ""} onChange={(e) => onCategoryChange?.(e.target.value)}>
                <option value="">All categories</option>
                {categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
              </select>
            </div>
          )}
          <div className="ml-auto text-[10px] text-muted-foreground">
            {customStart && customEnd ? `${customStart} → ${customEnd}` : ""}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
