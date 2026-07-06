// Env-derived constants. In dev, Vite proxies /api and /run to the backend
// (see vite.config.ts), so an empty base (same-origin) works everywhere. Override
// with VITE_API_URL when the frontend is hosted separately from the backend.
export const API_BASE_URL = import.meta.env.VITE_API_URL ?? "";
export const TOKEN_KEY = "dealwing_token";
