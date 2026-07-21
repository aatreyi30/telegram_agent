import type { NextConfig } from "next";

// Only used as a fallback when NEXT_PUBLIC_API_URL isn't set (services/api.ts
// then calls relative "/api" paths, which this rewrite proxies to the backend).
// When NEXT_PUBLIC_API_URL *is* set, the browser calls the backend directly
// and this rewrite is simply unused.
const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  rewrites: async () => [
    { source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` },
  ],
};

export default nextConfig;
