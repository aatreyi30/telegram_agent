"use client";

import { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

export function Empty({ children }: { children?: ReactNode }) {
  return (
    <Card>
      <CardContent className="p-10 text-center text-sm text-muted-foreground">{children ?? "No data."}</CardContent>
    </Card>
  );
}

export function Async<T>({ q, children, rows = 1 }: {
  q: { data?: T; isLoading: boolean; error?: Error | null }; children: (data: T) => ReactNode; rows?: number;
}) {
  if (q.isLoading) {
    const h = rows * 80;
    return (
      <div className="flex items-center justify-center" style={{ minHeight: h }}>
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (q.error) return <Empty>{(q.error as Error).message || "An error occurred."}</Empty>;
  if (!q.data) return <Empty />;
  return <>{children(q.data)}</>;
}
