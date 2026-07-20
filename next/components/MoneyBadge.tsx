"use client";

import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { moneyChip } from "@/lib/format";

/**
 * Honest earnings signal for a post: green "Earns" only when the merchant actually
 * pays a commission; amber "Shortened only" for AJIO/Myntra/etc. where the old UI
 * lied with a green "affiliate links" badge. Hover explains why.
 */
export function MoneyBadge({ affiliateStatus, merchant }: { affiliateStatus?: string | null; merchant?: string | null }) {
  const chip = moneyChip(affiliateStatus, merchant);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge variant={chip.tone} className="cursor-default font-medium">{chip.label}</Badge>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">{chip.hint}</TooltipContent>
    </Tooltip>
  );
}
