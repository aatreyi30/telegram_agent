import { cn } from "@/lib/utils";

// DealWing mark — a Telegram-style paper plane with wings.
export function LogoMark({ className, size = 32 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={className} aria-hidden>
      <defs>
        <linearGradient id="dwg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2AABEE" />
          <stop offset="1" stopColor="#229ED9" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="14" fill="url(#dwg)" />
      <path d="M8 30 L30 26 L20 34 Z" fill="#ffffff" opacity="0.55" />
      <path d="M8 40 L28 33 L22 42 Z" fill="#ffffff" opacity="0.4" />
      <path d="M50 16 L30 46 L27 35 L18 31 Z" fill="#ffffff" />
      <path d="M50 16 L34 38 L27 35 Z" fill="#ffffff" opacity="0.8" />
    </svg>
  );
}

export function Logo({ className, collapsed = false }: { className?: string; collapsed?: boolean }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <LogoMark size={30} />
      {!collapsed && (
        <span className="text-lg font-bold tracking-tight">
          Deal<span className="text-primary">Wing</span>
        </span>
      )}
    </div>
  );
}
