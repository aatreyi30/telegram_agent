import { ReactNode, useEffect } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

// Lightweight modal (no Radix). Controlled via `open`/`onClose`.
export function Dialog({ open, onClose, children, title, className }: {
  open: boolean; onClose: () => void; children: ReactNode; title?: string; className?: string;
}) {
  useEffect(() => {
    function esc(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    if (open) document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="fixed inset-0 bg-black/60 animate-fade-in" onClick={onClose} />
      <div className={cn("relative z-10 w-full max-w-md rounded-xl border bg-card p-6 shadow-xl animate-fade-in", className)}>
        <div className="mb-4 flex items-center justify-between">
          {title && <h3 className="text-lg font-semibold">{title}</h3>}
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground"><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}
