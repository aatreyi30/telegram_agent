import type { EmojiPolicy, StrategyRationale } from "@/types/api";

/** The AI's actual per-post justification — why this type, why this window, why this
 * deal, each backed by a real stat from context.py's grounded bundle, not free text.
 * Shared by Drafts and Queue-originated posts alike (both now return `rationale`). */
export function hasRationale(r: StrategyRationale | null | undefined): boolean {
  if (!r) return false;
  const ep: Partial<EmojiPolicy> = r.emoji_policy || {};
  return !!(r.why_type || r.target_window_ist?.why || ep.avoid?.length || r.why_this_deal?.why);
}

export function ReasoningPanel({ rationale }: { rationale: StrategyRationale | null | undefined }) {
  if (!hasRationale(rationale)) {
    return <p className="text-xs text-muted-foreground">No AI reasoning recorded for this post.</p>;
  }
  const r = rationale!;
  const ep: Partial<EmojiPolicy> = r.emoji_policy || {};
  return (
    <div className="space-y-1.5 text-xs text-muted-foreground">
      {r.why_type && <div><span className="font-medium text-foreground">Why this post:</span> {r.why_type}</div>}
      {r.target_window_ist?.why && <div><span className="font-medium text-foreground">Best time:</span> {r.target_window_ist.why}</div>}
      {!!ep.avoid?.length && (
        <div><span className="font-medium text-foreground">Emoji policy:</span> lead {(ep.lead || []).join(" ")}; stripped {(ep.avoid || []).join(" ")}</div>
      )}
      {r.why_this_deal?.why && <div><span className="font-medium text-foreground">Why this deal:</span> {r.why_this_deal.why}</div>}
      {r.note && <div><span className="font-medium text-foreground">Note:</span> {r.note}</div>}
    </div>
  );
}
