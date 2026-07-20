"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";
import { queryKeys } from "./keys";
import type {
  AnalyticsResponse, ChannelsResponse, CompetitorDashboardResponse, CompetitorDashboardTrendsResponse,
  CompetitorsResponse,
  DailyBrief, DataRangeResponse, DayResponse, DigestResponse, DraftsResponse, GrowthResponse, InsightsResponse,
  OrgResponse, OverviewResponse, PostsResponse,
  QueueResponse, RetroLatest, SchedulerRunsResponse, UsersResponse, WeeklyBrief,
} from "@/types/api";

export function useOverview() {
  return useQuery({ queryKey: queryKeys.overview(), queryFn: () => api.get<OverviewResponse>("/overview") });
}
export function useInsights(start?: string | null, end?: string | null, opts?: { enabled?: boolean }) {
  const qs = start && end ? `?start=${start}&end=${end}` : "";
  return useQuery({
    queryKey: queryKeys.insights(start, end),
    queryFn: () => api.get<InsightsResponse>(`/insights${qs}`),
    enabled: opts?.enabled,
  });
}
export function useDataRange() {
  return useQuery({ queryKey: queryKeys.dataRange(), queryFn: () => api.get<DataRangeResponse>("/data-range") });
}
export function useAnalytics(start?: string | null, end?: string | null, opts?: { enabled?: boolean }) {
  const qs = start && end ? `?start=${start}&end=${end}` : "";
  return useQuery({
    queryKey: queryKeys.analytics(start, end),
    queryFn: () => api.get<AnalyticsResponse>(`/analytics${qs}`),
    enabled: opts?.enabled,
  });
}
export function useDay(date?: string | null, end?: string | null, opts?: { enabled?: boolean }) {
  const qs = date ? `?date=${date}${end ? `&end=${end}` : ""}` : "";
  return useQuery({
    queryKey: queryKeys.day(date, end),
    queryFn: () => api.get<DayResponse>(`/day${qs}`),
    enabled: opts?.enabled,
  });
}
export function useDrafts(page: number, pageSize = 8) {
  return useQuery({
    queryKey: queryKeys.drafts(page),
    queryFn: () => api.get<DraftsResponse>(`/drafts?page=${page}&page_size=${pageSize}`),
  });
}
export function usePosts(page: number, pageSize = 20) {
  return useQuery({
    queryKey: queryKeys.posts(page),
    queryFn: () => api.get<PostsResponse>(`/posts?page=${page}&page_size=${pageSize}`),
  });
}
export function useQueue(page: number, pageSize = 15) {
  return useQuery({
    queryKey: queryKeys.queue(page),
    queryFn: () => api.get<QueueResponse>(`/queue?page=${page}&page_size=${pageSize}`),
  });
}
export function useCompetitors() {
  return useQuery({ queryKey: queryKeys.competitors(), queryFn: () => api.get<CompetitorsResponse>("/competitors") });
}
export function useCompetitorDashboard(window?: number | null) {
  return useQuery({
    queryKey: queryKeys.competitorDashboard(window),
    queryFn: () => api.get<CompetitorDashboardResponse>(`/competitor-dashboard${window ? `?window=${window}` : ""}`),
  });
}
export function useCompetitorDashboardTrends(days: number = 30) {
  return useQuery({
    queryKey: queryKeys.competitorDashboardTrends(days),
    queryFn: () => api.get<CompetitorDashboardTrendsResponse>(`/competitor-dashboard/trends?days=${days}`),
  });
}
export function useGrowth(start?: string | null, end?: string | null, opts?: { enabled?: boolean }) {
  const qs = start && end ? `?start=${start}&end=${end}` : "";
  return useQuery({
    queryKey: queryKeys.growth(start, end),
    queryFn: () => api.get<GrowthResponse>(`/growth${qs}`),
    enabled: opts?.enabled,
  });
}
export function useOrg() {
  return useQuery({ queryKey: queryKeys.org(), queryFn: () => api.get<OrgResponse>("/org") });
}
export function useChannels() {
  return useQuery({ queryKey: queryKeys.channels(), queryFn: () => api.get<ChannelsResponse>("/channels") });
}
export function useUsers() {
  return useQuery({ queryKey: queryKeys.users(), queryFn: () => api.get<UsersResponse>("/users") });
}
export function useDigest() {
  return useQuery({ queryKey: queryKeys.digest(), queryFn: () => api.get<DigestResponse>("/digest") });
}
export function useDailyBrief(date?: string | null) {
  const qs = date ? `?date=${date}` : "";
  return useQuery({
    queryKey: queryKeys.dailyBrief(date),
    queryFn: () => api.get<DailyBrief>(`/plan/daily${qs}`),
  });
}
export function useWeeklyBrief(end?: string | null) {
  const qs = end ? `?end=${end}` : "";
  return useQuery({
    queryKey: queryKeys.weeklyBrief(end),
    queryFn: () => api.get<WeeklyBrief>(`/plan/weekly${qs}`),
  });
}
export function useSchedulerRuns(job?: string | null) {
  const qs = job ? `?job=${job}` : "";
  return useQuery({
    queryKey: queryKeys.schedulerRuns(job),
    queryFn: () => api.get<SchedulerRunsResponse>(`/schedulers/runs${qs}`),
  });
}
export function useLatestRetro(week?: string | null) {
  const qs = week ? `?week=${week}` : "";
  return useQuery({
    queryKey: queryKeys.retroLatest(week),
    queryFn: () => api.get<RetroLatest>(`/retro/latest${qs}`),
  });
}
