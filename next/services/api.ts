import axios from "axios";

// NEXT_PUBLIC_API_URL (e.g. http://localhost:8000) points the browser directly
// at the backend. Falls back to a relative "/api" (relying on next.config.ts's
// rewrite proxy) when unset, so local dev without the env var still works.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ? `${process.env.NEXT_PUBLIC_API_URL}/api` : "/api";

const client = axios.create({ baseURL: API_BASE });

client.interceptors.request.use((config) => {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

client.interceptors.response.use(
  (res) => res.data?.data ?? res.data,
  (err) => {
    if (err.response?.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      window.location.href = "/login";
    }
    return Promise.reject(err.response?.data?.error || err.message || "Request failed");
  },
);

// The response interceptor above unwraps the {success,data,error} envelope at
// runtime, so callers get the real payload, not an AxiosResponse — but axios's
// own `get<T>`/`post<T>` signatures still type the return as `AxiosResponse<T>`.
// Wrap with an explicit cast so static types match actual runtime behavior
// (same pattern as the Vite app's services/api.ts).
export const api = {
  get: <T>(path: string) => client.get(path) as unknown as Promise<T>,
  post: <T>(path: string, body?: unknown) => client.post(path, body) as unknown as Promise<T>,
  put: <T>(path: string, body?: unknown) => client.put(path, body) as unknown as Promise<T>,
  patch: <T>(path: string, body?: unknown) => client.patch(path, body) as unknown as Promise<T>,
  del: <T>(path: string) => client.delete(path) as unknown as Promise<T>,
};
