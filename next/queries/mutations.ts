"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/services/api";
import type { DailyBrief, WeeklyBrief } from "@/types/api";
import { queryKeys } from "./keys";

export function useChangePassword() {
  return useMutation({ mutationFn: (body: { old_password: string; new_password: string }) => api.post("/auth/change-password", body) });
}
export function useUpdateOrg() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; settings: Record<string, unknown> }) => api.patch("/org", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.org() }),
  });
}
export function useAddChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; kind: string }) => api.post("/channels", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.channels() }),
  });
}
export function useDeleteChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.del(`/channels/${id}?confirm=true`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.channels() }),
  });
}
export function useCreateCompetitor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; category: string }) => api.post("/competitors", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.competitors() });
      qc.invalidateQueries({ queryKey: queryKeys.competitorDashboard() });
    },
  });
}
export function useUpdateCompetitor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; category?: string; title?: string; monitoring_enabled?: boolean }) =>
      api.patch(`/competitors/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.competitors() });
      qc.invalidateQueries({ queryKey: queryKeys.competitorDashboard() });
    },
  });
}
export function useDeleteCompetitor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.del(`/competitors/${id}?confirm=true`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.competitors() });
      qc.invalidateQueries({ queryKey: queryKeys.competitorDashboard() });
    },
  });
}
export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; email: string; password: string; role: string }) => api.post("/users", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.users() }),
  });
}
export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.del(`/users/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.users() }),
  });
}
export function useUpdateUserRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, role }: { id: number; role: string }) => api.patch(`/users/${id}`, { role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.users() }),
  });
}

// Draft mutations
export function useCreateDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { text: string; post_type?: string; selection_bucket?: string; channel_ref?: string }) => 
      api.post("/drafts", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.drafts() }),
  });
}

export function useUpdateDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; text?: string; post_type?: string; status?: string; selection_bucket?: string; channel_ref?: string }) => 
      api.put(`/drafts/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.drafts() }),
  });
}

export function useDeleteDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.del(`/drafts/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.drafts() }),
  });
}

// Steer & Regenerate — Plan tab
export function useRegenerateDailyPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { date?: string; directive?: string }) => api.post<DailyBrief>("/plan/daily/regenerate", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.dailyBriefAll() });
      qc.invalidateQueries({ queryKey: queryKeys.retroLatestAll() });
    },
  });
}
export function useRegenerateWeeklyPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { end?: string; directive?: string }) => api.post<WeeklyBrief>("/plan/weekly/regenerate", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.weeklyBriefAll() });
      qc.invalidateQueries({ queryKey: queryKeys.retroLatestAll() });
    },
  });
}
