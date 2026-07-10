/** Centralized query-key factory — every hook in queries.ts/mutations.ts builds
 * its key here so invalidation stays consistent (no magic string arrays
 * scattered across route files, no accidental key mismatches between the
 * query and the mutation that should invalidate it). */
export const queryKeys = {
  overview: () => ["overview"] as const,
  insights: () => ["insights"] as const,
  analytics: (start?: string | null, end?: string | null) => ["analytics", start ?? null, end ?? null] as const,
  dataRange: () => ["data-range"] as const,
  day: (date?: string | null) => ["day", date ?? null] as const,
  drafts: (page: number) => ["drafts", page] as const,
  posts: (page: number) => ["posts", page] as const,
  queue: (page: number) => ["queue", page] as const,
  competitors: () => ["competitors"] as const,
  competitorDashboard: (window?: number | null) => ["competitor-dashboard", window ?? null] as const,
  merchants: () => ["merchants"] as const,
  plans: () => ["plans"] as const,
  weekly: () => ["weekly"] as const,
  growth: () => ["growth"] as const,
  org: () => ["org"] as const,
  channels: () => ["channels"] as const,
  users: () => ["users"] as const,
};
