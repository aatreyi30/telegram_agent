"use client";

import { ReactNode } from "react";
import { Skeleton } from "@/components/Reveal";

export function Empty({ children }: { children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-card p-10 text-center text-sm text-muted-foreground">
      {children ?? "No data."}
    </div>
  );
}

export function Async<T>({ q, children, rows = 1 }: {
  q: { data?: T; isLoading: boolean; error?: Error | null }; children: (data: T) => ReactNode; rows?: number;
}) {
  if (q.isLoading) {
    // Shimmer skeleton cards instead of a bare spinner — reads as "loading real
    // content", not "frozen", and matches the agentic, alive feel.
    return (
      <div className="space-y-3">
        {Array.from({ length: Math.max(1, rows) }).map((_, i) => (
          <div key={i} className="reveal rounded-xl border border-border bg-card p-5" style={{ "--d": `${i * 80}ms` } as React.CSSProperties}>
            <Skeleton className="h-4 w-1/3" />
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          </div>
        ))}
      </div>
    );
  }
  if (q.error) return <Empty>{(q.error as Error).message || "An error occurred."}</Empty>;
  if (!q.data) return <Empty />;
  return <>{children(q.data)}</>;
}
