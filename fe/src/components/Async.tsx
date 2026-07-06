import { UseQueryResult } from "@tanstack/react-query";
import { ReactNode } from "react";
import { Skeleton } from "./ui/primitives";

// Renders loading skeletons / error / content for a react-query result.
export function Async<T>({ q, children, rows = 3 }: {
  q: UseQueryResult<T>; children: (data: T) => ReactNode; rows?: number;
}) {
  if (q.isLoading)
    return (
      <div className="space-y-3">
        {Array.from({ length: rows }).map((_, i) => (
          <Skeleton key={i} className="h-24 w-full" />
        ))}
      </div>
    );
  if (q.isError)
    return (
      <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
        Couldn't load: {(q.error as Error)?.message || "error"}
      </div>
    );
  return <>{children(q.data as T)}</>;
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}
