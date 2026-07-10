"use client";

import { useCallback } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";

export function useQueryParams() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const get = useCallback(
    (key: string, defaultVal = "") => searchParams.get(key) ?? defaultVal,
    [searchParams],
  );

  const set = useCallback(
    (params: Record<string, string | null>, scroll = false) => {
      const sp = new URLSearchParams(searchParams.toString());
      for (const [k, v] of Object.entries(params)) {
        if (v === null || v === undefined) sp.delete(k);
        else sp.set(k, v);
      }
      const qs = sp.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll });
    },
    [searchParams, router, pathname],
  );

  return { get, set, searchParams };
}
