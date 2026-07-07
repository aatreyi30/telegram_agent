import type { DatePreset } from "@/types/ui";

export const DEFAULT_DATE_PRESETS: DatePreset[] = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "All", days: "all" },
];
