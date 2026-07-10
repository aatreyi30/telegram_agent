"use client";

import { Badge } from "@/components/ui/badge";
import type { CompetitorEntity } from "@/types/api";

/**
 * Direct (platform) / Indirect (channel) competitor classification badge — shared between the
 * competitor dashboard table and the Settings > Competitors tab list.
 */
export function CategoryBadge({ category }: { category?: CompetitorEntity["category"] }) {
  if (category === "platform") return <Badge variant="primary" className="text-[10px] font-normal">Direct</Badge>;
  if (category === "channel") return <Badge variant="outline" className="text-[10px] font-normal">Indirect</Badge>;
  return null;
}
