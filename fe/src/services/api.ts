// Axios client for the DealWing API.
// - attaches the Bearer token
// - unwraps the { success, data, error } envelope so callers get `data` directly
// - throws ApiError on non-2xx / success:false; on 401 clears the token and
//   redirects to /login.

import axios, { AxiosError } from "axios";
import { API_BASE_URL, TOKEN_KEY } from "@/constants/env";
import { ApiError } from "@/lib/errors";

export { ApiError };

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t: string | null) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

const client = axios.create({ baseURL: API_BASE_URL });

client.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

client.interceptors.response.use(
  (response) => {
    const body = response.data;
    // enveloped responses: { success, data, error }
    if (body && typeof body === "object" && "success" in body) {
      if (body.success) return body.data;
      throw new ApiError(response.status, body.error?.message ?? "Request failed", body.error?.details);
    }
    return body;
  },
  (err: AxiosError<any>) => {
    const status = err.response?.status ?? 0;
    if (status === 401) {
      setToken(null);
      if (!location.pathname.startsWith("/login")) location.href = "/login";
    }
    const body = err.response?.data as any;
    const message = body?.error?.message || body?.message || err.message || "Request failed";
    throw new ApiError(status, message, body?.error?.details);
  }
);

export const api = {
  get: <T>(path: string) => client.get(path) as unknown as Promise<T>,
  post: <T>(path: string, body?: unknown) => client.post(path, body) as unknown as Promise<T>,
  patch: <T>(path: string, body?: unknown) => client.patch(path, body) as unknown as Promise<T>,
  del: <T>(path: string) => client.delete(path) as unknown as Promise<T>,
};
