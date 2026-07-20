"use client";

import { useState } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { Add01Icon, Delete02Icon, GridViewIcon, SaleTag01Icon } from "@hugeicons/core-free-icons";
import { Async } from "@/components/Async";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useOrg } from "@/queries/queries";
import { useUpdateOrg } from "@/queries/mutations";
import type { PostTemplateKey, PostTemplates } from "@/types/api";
import { OwnerOnly } from "../owner-guard";
import { Note } from "../note";

type PrimaryBlockKey = "deal" | "loot";

// The two post types an operator edits day to day. Each opens a right-side sheet
// listing the FULL example posts the AI mimics, one per numbered block. Blocks map
// 1:1 to the `examples` array (JSON string[]) the copywriter reads as exemplars —
// block 1 is examples[0] (primary), the rest are examples[1..]. No first-line/rest
// split: each block is one complete post edited as-is.
const PRIMARY_BLOCKS: Record<PrimaryBlockKey, {
  label: string; description: string; icon: typeof SaleTag01Icon;
  examples: PostTemplateKey;
}> = {
  deal: {
    label: "Deal",
    description: "Single-item deal post — price line + verified coupon proof.",
    icon: SaleTag01Icon,
    examples: "_deal_examples",
  },
  loot: {
    label: "Loot",
    description: "Multi-category loot board — themed banner + one category-link per line.",
    icon: GridViewIcon,
    examples: "_loot_examples",
  },
};

function parseExamples(raw?: string): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function serializeExamples(examples: string[]): string {
  return JSON.stringify(examples);
}

function TemplatesTab() {
  const q = useOrg();
  const updateOrg = useUpdateOrg();
  const [form, setForm] = useState<PostTemplates | null>(null);
  const [note, setNote] = useState<{ ok: boolean; msg: string } | null>(null);
  const [openType, setOpenType] = useState<PrimaryBlockKey | null>(null);

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

  const activeBlock = openType ? PRIMARY_BLOCKS[openType] : null;

  // Each block is one full example post; the whole list round-trips through the
  // examples key the copywriter reads. Block 1 is examples[0].
  const examples = templates && activeBlock ? parseExamples(templates[activeBlock.examples]) : [];

  function setExamples(next: string[]) {
    if (!activeBlock) return;
    setForm({ ...(templates ?? {}), [activeBlock.examples]: serializeExamples(next) });
  }
  function updateExample(i: number, value: string) {
    // Fall back to a one-slot list so editing block 1 persists even before any exist.
    const list = examples.length ? examples : [""];
    setExamples(list.map((e, idx) => (idx === i ? value : e)));
  }
  function addExample() {
    setExamples([...examples, ""]);
  }
  function removeExample(i: number) {
    setExamples(examples.filter((_, idx) => idx !== i));
  }

  return (
    <Async q={q} rows={2}>
      {() =>
        templates && (
          <div className="space-y-4">
            <p className="max-w-2xl text-sm text-muted-foreground">
              These are the example posts the AI mimics when it writes. Each numbered block is one
              complete post — write it exactly as you want it to read, using real values and{" "}
              <span className="font-mono">&lt;link/&gt;</span> / <span className="font-mono">&lt;LINK_n&gt;</span> tokens
              where a live link goes.
            </p>

            {/* Two clickable nav cards — click to open the editor sheet for that type. */}
            <div className="grid max-w-xl grid-cols-2 gap-4">
              {(Object.keys(PRIMARY_BLOCKS) as PrimaryBlockKey[]).map((k) => {
                const block = PRIMARY_BLOCKS[k];
                const isActive = openType === k;
                return (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setOpenType(k)}
                    className="text-left"
                    aria-pressed={isActive}
                  >
                    <Card
                      className={cn(
                        "cursor-pointer transition-all duration-200",
                        isActive
                          ? "border-primary/40 bg-muted/60 ring-1 ring-primary/20"
                          : "hover-lift hover:border-muted-foreground/40"
                      )}
                    >
                      <CardHeader>
                        <div className="flex items-center gap-2.5">
                          <span
                            className={cn(
                              "flex size-9 items-center justify-center rounded-lg transition-colors",
                              isActive ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"
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

            <div className="flex items-center gap-3">
              <Button onClick={save} disabled={updateOrg.isPending}>
                {updateOrg.isPending ? "Saving…" : "Save templates"}
              </Button>
              {note && <Note {...note} />}
            </div>

            <Sheet open={openType !== null} onOpenChange={(o) => !o && setOpenType(null)}>
              <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
                {activeBlock && (
                  <>
                    <SheetHeader>
                      <SheetTitle className="flex items-center gap-2">
                        <span className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                          <HugeiconsIcon icon={activeBlock.icon} size={16} />
                        </span>
                        {activeBlock.label}
                      </SheetTitle>
                      <SheetDescription>{activeBlock.description}</SheetDescription>
                    </SheetHeader>

                    <ul className="space-y-3 px-4 pb-4">
                      {/* Each block is one full example post. Block 1 (examples[0]) is the
                          primary and always present; extras are removable. */}
                      {(examples.length ? examples : [""]).map((value, i) => (
                        <li key={i} className="group flex gap-3 rounded-lg border border-border bg-card p-3">
                          <span
                            className={cn(
                              "mt-1 flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                              i === 0
                                ? "bg-primary text-primary-foreground"
                                : "border border-primary bg-primary/10 text-primary"
                            )}
                          >
                            {i + 1}
                          </span>
                          <Textarea
                            rows={i === 0 ? 5 : 4}
                            value={value}
                            onChange={(e) => updateExample(i, e.target.value)}
                            className="border-0 bg-transparent px-0 py-0 font-mono text-sm shadow-none focus-visible:ring-0"
                          />
                          {i > 0 && (
                            <button
                              type="button"
                              onClick={() => removeExample(i)}
                              className="mt-1 shrink-0 rounded-md p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-destructive group-hover:opacity-100"
                              aria-label="Remove block"
                            >
                              <HugeiconsIcon icon={Delete02Icon} size={16} />
                            </button>
                          )}
                        </li>
                      ))}

                      <li>
                        <button
                          type="button"
                          onClick={addExample}
                          className="flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed border-border py-2 text-sm text-muted-foreground transition-colors hover:border-muted-foreground/50 hover:text-foreground"
                        >
                          <HugeiconsIcon icon={Add01Icon} size={16} />
                          Add
                        </button>
                      </li>
                    </ul>
                  </>
                )}
              </SheetContent>
            </Sheet>
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
