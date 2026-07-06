import { createContext, useContext, ReactNode } from "react";
import { cn } from "@/lib/utils";

const TabsCtx = createContext<{ value: string; setValue: (v: string) => void }>({
  value: "",
  setValue: () => {},
});

export function Tabs({ value, onValueChange, children, className }: {
  value: string; onValueChange: (v: string) => void; children: ReactNode; className?: string;
}) {
  return <TabsCtx.Provider value={{ value, setValue: onValueChange }}><div className={className}>{children}</div></TabsCtx.Provider>;
}

export function TabsList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("inline-flex h-10 items-center gap-1 rounded-lg bg-muted p-1 text-muted-foreground", className)}>
      {children}
    </div>
  );
}

export function TabsTrigger({ value, children }: { value: string; children: ReactNode }) {
  const ctx = useContext(TabsCtx);
  const active = ctx.value === value;
  return (
    <button
      onClick={() => ctx.setValue(value)}
      className={cn(
        "inline-flex items-center justify-center rounded-md px-3 py-1.5 text-sm font-medium transition-all",
        active ? "bg-background text-foreground shadow-sm" : "hover:text-foreground"
      )}
    >
      {children}
    </button>
  );
}

export function TabsContent({ value, children, className }: { value: string; children: ReactNode; className?: string }) {
  const ctx = useContext(TabsCtx);
  if (ctx.value !== value) return null;
  return <div className={cn("mt-4 animate-fade-in", className)}>{children}</div>;
}
