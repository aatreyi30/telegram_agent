"use client";

import { Fragment, ReactNode } from "react";
import { cn } from "@/lib/utils";

// Telegram markdown the copywriter emits: **bold**, __italic__, `code`, and bare URLs.
// Render it the way it will actually look in the channel, so the operator sees the real
// post — not raw "**91% OFF**" asterisks (which is what the old <pre> dump showed).
const TOKEN = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|https?:\/\/[^\s]+)/g;

function renderInline(text: string): ReactNode[] {
  return text.split(TOKEN).map((part, i) => {
    if (!part) return null;
    if (part.startsWith("**") && part.endsWith("**"))
      return <strong key={i} className="font-semibold text-foreground">{part.slice(2, -2)}</strong>;
    if (part.startsWith("__") && part.endsWith("__"))
      return <em key={i}>{part.slice(2, -2)}</em>;
    if (part.startsWith("`") && part.endsWith("`"))
      return <code key={i} className="rounded bg-muted px-1 py-0.5 text-[0.85em]">{part.slice(1, -1)}</code>;
    if (/^https?:\/\//.test(part))
      return (
        <a key={i} href={part} target="_blank" rel="noreferrer"
          className="break-all text-primary underline underline-offset-2 hover:opacity-80">
          {part}
        </a>
      );
    return <Fragment key={i}>{part}</Fragment>;
  });
}

/**
 * Renders a generated post as it will appear in Telegram — bold/italic/code applied,
 * links live and clickable, spacing preserved. `dense` trims the chrome for use inside
 * a table row / drawer.
 */
export function PostPreview({ text, className, dense = false }: { text: string; className?: string; dense?: boolean }) {
  const lines = (text || "").split("\n");
  return (
    <div
      className={cn(
        "whitespace-pre-wrap break-words rounded-lg border bg-muted/30 text-sm leading-relaxed text-foreground/90",
        dense ? "p-3" : "p-4",
        className,
      )}
    >
      {lines.map((line, i) => (
        <div key={i} className={line.trim() === "" ? "h-2" : undefined}>
          {renderInline(line)}
        </div>
      ))}
    </div>
  );
}
