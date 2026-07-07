"use client";

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
export function useDay(date?: string | null, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.day(date),
    queryFn: () => api.get<DayResponse>(`/day${date ? `?date=${date}` : ""}`),
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
export function useMerchants() {
  return useQuery({ queryKey: queryKeys.merchants(), queryFn: () => api.get<MerchantsResponse>("/merchants") });
}
export function usePlans() {
  return useQuery({ queryKey: queryKeys.plans(), queryFn: () => api.get<PlansResponse>("/plans") });
}
export function useWeekly() {
  return useQuery({ queryKey: queryKeys.weekly(), queryFn: () => api.get<WeeklyResponse>("/weekly") });
}
export function useGrowth() {
  return useQuery({ queryKey: queryKeys.growth(), queryFn: () => api.get<GrowthResponse>("/growth") });
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
