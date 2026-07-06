import { ReactNode } from "react";
import { Card } from "./ui/card";

export function StatCard({ label, value, sub, icon }: {
  label: string; value: ReactNode; sub?: string; icon?: ReactNode;
}) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-2xl font-bold tracking-tight">{value}</div>
          <div className="mt-1 text-sm text-muted-foreground">{label}</div>
        </div>
        {icon && <div className="text-primary/70">{icon}</div>}
      </div>
      {sub && <div className="mt-2 text-xs text-muted-foreground">{sub}</div>}
    </Card>
  );
}
