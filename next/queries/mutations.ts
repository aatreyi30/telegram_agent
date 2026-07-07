"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/services/api";
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
