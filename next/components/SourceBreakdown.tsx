import { Badge } from "@/components/ui/badge";
import { StackedBarsChart } from "@/components/charts";
import type { SourceBreakdown } from "@/types/api";

// "humanize" a raw source/metric key ("search_engine" -> "Search engine") for legends/labels.
function humanizeLabel(key: string): string {
  const s = key.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Reshape a Telegram broadcast-stats source breakdown ({totals, daily}) into the
// {label, [source]: value}[] row format StackedBarsChart expects.
function sourceRows(sb: SourceBreakdown) {
  return Object.entries(sb.daily)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, sources]) => ({ label: date, ...sources }));
}

function SourceBreakdownChart({ title, sb }: { title: string; sb: SourceBreakdown }) {
  const keys = Object.keys(sb.totals);
  const rows = sourceRows(sb);
  const chartKeys = keys.map((k) => ({ key: k, name: humanizeLabel(k) }));
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      <StackedBarsChart data={rows} keys={chartKeys} unit="" height={200} />
      <div className="flex flex-wrap gap-1.5">
        {keys.map((k) => (
          <Badge key={k} variant="outline" className="text-xs">
            {humanizeLabel(k)}: {sb.totals[k].toLocaleString()}
          </Badge>
        ))}
      </div>
    </div>
  );
}

/** True when there's at least one source-breakdown chart worth rendering — lets
 * callers skip wrapping chrome (card/title) entirely instead of showing it empty. */
export function hasSourceBreakdown(
  viewSources?: SourceBreakdown | null,
  followerSources?: SourceBreakdown | null,
): boolean {
  const hasViews = !!viewSources && Object.keys(viewSources.totals).length > 0;
  const hasFollowers = !!followerSources && Object.keys(followerSources.totals).length > 0;
  return hasViews || hasFollowers;
}

// Renders the view/follower "by source" stacked charts when Telegram broadcast stats are
// available for the channel (Channel.can_view_stats); renders nothing (no placeholder, no
// error) when absent.
export function SourceBreakdownSection({ viewSources, followerSources }: {
  viewSources?: SourceBreakdown | null; followerSources?: SourceBreakdown | null;
}) {
  const hasViews = !!viewSources && Object.keys(viewSources.totals).length > 0;
  const hasFollowers = !!followerSources && Object.keys(followerSources.totals).length > 0;
  if (!hasViews && !hasFollowers) return null;
  return (
    <div className="space-y-4">
      {hasViews && <SourceBreakdownChart title="Views by source" sb={viewSources!} />}
      {hasFollowers && <SourceBreakdownChart title="Joins by source" sb={followerSources!} />}
    </div>
  );
}
