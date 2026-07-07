/** Typed read hooks for every `/api/*` GET endpoint — one hook per resource
 * instead of each route inlining `useQuery({queryKey: [...], queryFn: () =>
 * api.get<any>(...)})`. Route components should import from here, not call
 * `api.get` directly (mutations.ts is the equivalent for writes). */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";
import { queryKeys } from "./keys";
import type {
  AnalyticsResponse, ChannelsResponse, CompetitorDashboardResponse, CompetitorsResponse,
  DataRangeResponse, DayResponse, DraftsResponse, GrowthResponse, InsightsResponse,
  MerchantsResponse, OrgResponse, OverviewResponse, PlansResponse, PostsResponse,
  QueueResponse, UsersResponse, WeeklyResponse,
} from "@/types/api";

export function useOverview() {
  return useQuery({ queryKey: queryKeys.overview(), queryFn: () => api.get<OverviewResponse>("/api/overview") });
}

export function useInsights() {
  return useQuery({ queryKey: queryKeys.insights(), queryFn: () => api.get<InsightsResponse>("/api/insights") });
}

export function useDataRange() {
  return useQuery({ queryKey: queryKeys.dataRange(), queryFn: () => api.get<DataRangeResponse>("/api/data-range") });
}

/** `start`/`end` are YYYY-MM-DD (IST calendar dates), matching the backend's expectation.
 * Pass `enabled: false` while a prerequisite (e.g. the data-range query) is still loading,
 * so this doesn't fire an unscoped "all time" fetch that gets immediately replaced. */
export function useAnalytics(start?: string | null, end?: string | null, opts?: { enabled?: boolean }) {
  const qs = start && end ? `?start=${start}&end=${end}` : "";
  return useQuery({
    queryKey: queryKeys.analytics(start, end),
    queryFn: () => api.get<AnalyticsResponse>(`/api/analytics${qs}`),
    enabled: opts?.enabled,
  });
}

export function useDay(date?: string | null, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.day(date),
    queryFn: () => api.get<DayResponse>(`/api/day${date ? `?date=${date}` : ""}`),
    enabled: opts?.enabled,
  });
}

export function useDrafts(page: number, pageSize = 8) {
  return useQuery({
    queryKey: queryKeys.drafts(page),
    queryFn: () => api.get<DraftsResponse>(`/api/drafts?page=${page}&page_size=${pageSize}`),
  });
}

export function usePosts(page: number, pageSize = 20) {
  return useQuery({
    queryKey: queryKeys.posts(page),
    queryFn: () => api.get<PostsResponse>(`/api/posts?page=${page}&page_size=${pageSize}`),
  });
}

export function useQueue(page: number, pageSize = 15) {
  return useQuery({
    queryKey: queryKeys.queue(page),
    queryFn: () => api.get<QueueResponse>(`/api/queue?page=${page}&page_size=${pageSize}`),
  });
}

export function useCompetitors() {
  return useQuery({ queryKey: queryKeys.competitors(), queryFn: () => api.get<CompetitorsResponse>("/api/competitors") });
}

export function useCompetitorDashboard(window?: number | null) {
  return useQuery({
    queryKey: queryKeys.competitorDashboard(window),
    queryFn: () => api.get<CompetitorDashboardResponse>(`/api/competitor-dashboard${window ? `?window=${window}` : ""}`),
  });
}

export function useMerchants() {
  return useQuery({ queryKey: queryKeys.merchants(), queryFn: () => api.get<MerchantsResponse>("/api/merchants") });
}

export function usePlans() {
  return useQuery({ queryKey: queryKeys.plans(), queryFn: () => api.get<PlansResponse>("/api/plans") });
}

export function useWeekly() {
  return useQuery({ queryKey: queryKeys.weekly(), queryFn: () => api.get<WeeklyResponse>("/api/weekly") });
}

export function useGrowth() {
  return useQuery({ queryKey: queryKeys.growth(), queryFn: () => api.get<GrowthResponse>("/api/growth") });
}

export function useOrg() {
  return useQuery({ queryKey: queryKeys.org(), queryFn: () => api.get<OrgResponse>("/api/org") });
}

export function useChannels() {
  return useQuery({ queryKey: queryKeys.channels(), queryFn: () => api.get<ChannelsResponse>("/api/channels") });
}

export function useUsers() {
  return useQuery({ queryKey: queryKeys.users(), queryFn: () => api.get<UsersResponse>("/api/users") });
}
