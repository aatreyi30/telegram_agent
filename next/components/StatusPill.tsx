"use client";

import { Badge } from "@/components/ui/badge";
import { statusLabel, statusTone } from "@/lib/format";
import { cn } from "@/lib/utils";

/** A queue/post/job status rendered as a plain-word, colour-coded pill. */
export function StatusPill({ status, className }: { status?: string | null; className?: string }) {
  return (
    <Badge variant={statusTone(status)} className={cn("font-medium", className)}>
      {statusLabel(status)}
    </Badge>
  );
}

/** A {status: count} map rendered as a row of plain-word pills ("Queued · 3"). */
export function StatusCounts({ counts }: { counts?: Record<string, number> | null }) {
  return (
    <>
      {Object.entries(counts || {}).map(([k, v]) => (
        <Badge key={k} variant={statusTone(k)} className="font-medium">{statusLabel(k)} · {v}</Badge>
      ))}
    </>
  );
}
