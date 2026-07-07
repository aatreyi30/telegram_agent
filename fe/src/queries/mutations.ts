/** Typed write hooks — each mutation invalidates exactly the query key(s) its
 * write affects, so cache invalidation is declared next to the write instead
 * of hand-rolled per call site. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/services/api";
import { queryKeys } from "./keys";

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { old_password: string; new_password: string }) =>
      api.post("/api/auth/change-password", body),
  });
}

export function useUpdateOrg() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name?: string; settings?: Record<string, unknown> }) => api.patch("/api/org", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.org() }),
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; email: string; password: string; role: string }) =>
      api.post("/api/users", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.users() }),
  });
}

export function useUpdateUserRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, role }: { id: number; role: string }) => api.patch(`/api/users/${id}`, { role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.users() }),
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.del(`/api/users/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.users() }),
  });
}

export function useAddChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; kind?: string }) => api.post("/api/channels", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.channels() }),
  });
}

export function useDeleteChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.del(`/api/channels/${id}?confirm=true`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.channels() }),
  });
}
