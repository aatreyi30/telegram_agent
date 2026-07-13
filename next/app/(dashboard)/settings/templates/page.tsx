"use client";

import { useState } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  CheckmarkCircle02Icon, GridViewIcon, SaleTag01Icon,
} from "@hugeicons/core-free-icons";
import { Async } from "@/components/Async";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useOrg } from "@/queries/queries";
import { useUpdateOrg } from "@/queries/mutations";
import type { PostTemplateKey, PostTemplates } from "@/types/api";
import { OwnerOnly } from "../owner-guard";
import { Note } from "../note";

type PrimaryBlockKey = "deal" | "loot";

// The two post types an operator edits day to day, each behind its own nav card
// and ONE paste-in textarea. Under the hood each still maps to 2 backend keys
// (a "first" line and a "rest" template) so the render pipeline is untouched —
// the split is just: first line -> `first`, everything after -> `rest`.
const PRIMARY_BLOCKS: Record<PrimaryBlockKey, {
  label: string; description: string; icon: typeof SaleTag01Icon;
  first: PostTemplateKey; rest: PostTemplateKey;
  placeholders: string; splitHint: string;
  // Per-type accent so Deal and Loot are visually distinct at a glance in the
  // nav — literal class strings (not built dynamically) so Tailwind's static
  // scanner picks them up.
  accentBar: string; iconIdle: string; iconActive: string; cardActive: string; check: string;
}> = {
  deal: {
    label: "Deal",
    description: "Single-item deal post — price line + verified coupon proof.",
    icon: SaleTag01Icon,
    first: "single_price",
    rest: "single_coupon_line",
    placeholders: "{price} {mrp} {discount} · {code} {time} {date}",
    splitHint: "First line = price line. Everything after = the coupon proof line.",
    accentBar: "bg-chart-4",
    iconIdle: "bg-chart-4/15 text-chart-4",
    iconActive: "bg-chart-4 text-white",
    cardActive: "border-chart-4 bg-chart-4/5 ring-1 ring-chart-4 shadow-md",
    check: "text-chart-4",
  },
  loot: {
    label: "Loot",
    description: "Multi-item loot board — ranked list under a themed banner.",
    icon: GridViewIcon,
    first: "collection_theme_default",
    rest: "collection_item",
    placeholders: "{date} · {n} {title} {raw_price} {discount} {link}",
    splitHint: "First line = banner theme. Everything after = the per-item line.",
    accentBar: "bg-chart-2",
    iconIdle: "bg-chart-2/15 text-chart-2",
    iconActive: "bg-chart-2 text-white",
    cardActive: "border-chart-2 bg-chart-2/5 ring-1 ring-chart-2 shadow-md",
    check: "text-chart-2",
  },
};

function TemplatesTab() {
  const q = useOrg();
  const updateOrg = useUpdateOrg();
  const [form, setForm] = useState<PostTemplates | null>(null);
  const [note, setNote] = useState<{ ok: boolean; msg: string } | null>(null);
  const [active, setActive] = useState<PrimaryBlockKey>("deal");

  // Prefill from the GET response until the operator starts editing.
  const templates: PostTemplates | null = form ?? (q.data ? { ...(q.data.settings?.post_templates ?? {}) } : null);

  async function save() {
    if (!templates || !q.data) return;
    setNote(null);
    try {
      // Partial-merge on the backend preserves the rest of settings; send the whole
      // post_templates object (org name comes along because useUpdateOrg requires it).
      await updateOrg.mutateAsync({ name: q.data.name, settings: { post_templates: templates } });
      setNote({ ok: true, msg: "Post templates saved." });
    } catch (e) {
      setNote({ ok: false, msg: (e as Error).message });
    }
  }

  const activeBlock = PRIMARY_BLOCKS[active];
  const combinedValue = templates
    ? [templates[activeBlock.first] ?? "", templates[activeBlock.rest] ?? ""]
        .filter((v, i) => v || i === 0)
        .join("\n")
    : "";

  function setCombined(raw: string) {
    const idx = raw.indexOf("\n");
    const first = idx === -1 ? raw : raw.slice(0, idx);
    const rest = idx === -1 ? "" : raw.slice(idx + 1);
    setForm({ ...(templates ?? {}), [activeBlock.first]: first, [activeBlock.rest]: rest });
  }

  return (
    <Async q={q} rows={2}>
      {() =>
        templates && (
          <div className="space-y-4">
            <p className="max-w-2xl text-sm text-muted-foreground">
              These templates control the exact wording of generated post text. Keep the
              curly-brace placeholders intact — they&apos;re replaced with live values at post time.
            </p>

            {/* Nav: two clickable cards, one per post type — color-accented so
                Deal (amber) and Loot (violet) are distinguishable at a glance */}
            <div className="grid max-w-xl grid-cols-2 gap-4">
              {(Object.keys(PRIMARY_BLOCKS) as PrimaryBlockKey[]).map((k) => {
                const block = PRIMARY_BLOCKS[k];
                const isActive = active === k;
                return (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setActive(k)}
                    className="relative text-left"
                    aria-pressed={isActive}
                  >
                    <Card
                      className={cn(
                        "cursor-pointer overflow-hidden transition-all duration-200",
                        isActive ? block.cardActive : cn("hover-lift hover:border-muted-foreground/40")
                      )}
                    >
                      <div className={cn("h-1.5 w-full transition-opacity", block.accentBar, isActive ? "opacity-100" : "opacity-25")} />
                      {isActive && (
                        <HugeiconsIcon
                          icon={CheckmarkCircle02Icon}
                          size={18}
                          className={cn("absolute right-3 top-4", block.check)}
                        />
                      )}
                      <CardHeader>
                        <div className="flex items-center gap-2.5">
                          <span
                            className={cn(
                              "flex size-9 items-center justify-center rounded-lg transition-colors",
                              isActive ? block.iconActive : block.iconIdle
                            )}
                          >
                            <HugeiconsIcon icon={block.icon} size={17} />
                          </span>
                          <CardTitle className="text-base font-semibold">{block.label}</CardTitle>
                        </div>
                        <CardDescription>{block.description}</CardDescription>
                      </CardHeader>
                    </Card>
                  </button>
                );
              })}
            </div>

            {/* The active card's single paste-in block */}
            <Card className="overflow-hidden">
              <div className={cn("h-1 w-full", activeBlock.accentBar)} />
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base font-semibold">
                  <HugeiconsIcon icon={activeBlock.icon} size={16} className={activeBlock.check} />
                  {activeBlock.label} template
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5">
                <Textarea
                  rows={6}
                  value={combinedValue}
                  onChange={(e) => setCombined(e.target.value)}
                  className="font-mono text-sm"
                />
                <p className="text-xs text-muted-foreground">
                  Placeholders: <span className="font-mono">{activeBlock.placeholders}</span>
                </p>
                <p className="text-xs text-muted-foreground">{activeBlock.splitHint}</p>
              </CardContent>
            </Card>

            <div className="flex items-center gap-3">
              <Button onClick={save} disabled={updateOrg.isPending}>
                {updateOrg.isPending ? "Saving…" : "Save templates"}
              </Button>
              {note && <Note {...note} />}
            </div>
          </div>
        )
      }
    </Async>
  );
}

export default function TemplatesPage() {
  return (
    <OwnerOnly>
      <TemplatesTab />
    </OwnerOnly>
  );
}