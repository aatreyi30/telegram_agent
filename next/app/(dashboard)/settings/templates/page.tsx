"use client";

import { useState } from "react";
import { Async } from "@/components/Async";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useOrg } from "@/queries/queries";
import { useUpdateOrg } from "@/queries/mutations";
import type { PostTemplateKey, PostTemplates } from "@/types/api";
import { OwnerOnly } from "../owner-guard";
import { Note } from "../note";

// Single source of truth for the editable templates: which fields exist, how they
// group, and the placeholders each one supports (shown as helper text so the
// operator knows what tokens are safe to use). Mirrors the 11 backend keys.
interface TemplateField {
  key: PostTemplateKey;
  label: string;
  placeholders: string; // "(none)" when the template takes no tokens
}
interface TemplateGroup {
  title: string;
  fields: TemplateField[];
}

const GROUPS: TemplateGroup[] = [
  {
    title: "Single deal",
    fields: [
      { key: "single_loot_badge", label: "Loot badge", placeholders: "(none)" },
      { key: "single_price", label: "Price line", placeholders: "{price} {mrp} {discount}" },
    ],
  },
  {
    title: "Collection",
    fields: [
      { key: "collection_theme_default", label: "Theme (default)", placeholders: "(none)" },
      { key: "collection_item", label: "Item line", placeholders: "{title} {price} {link}" },
    ],
  },
  {
    title: "Category",
    fields: [
      { key: "category_theme_with_tier", label: "Theme (with tier)", placeholders: "{emoji_start} {label} {tier} {emoji_end}" },
      { key: "category_theme_no_tier", label: "Theme (no tier)", placeholders: "{emoji_start} {label} {emoji_end}" },
      { key: "category_item", label: "Item line", placeholders: "{title} {price} {coupon} {link}" },
      { key: "category_coupon_suffix", label: "Coupon suffix", placeholders: "{code}" },
    ],
  },
  {
    title: "Fallbacks",
    fields: [
      { key: "observed_collection_theme", label: "Observed collection theme", placeholders: "(none)" },
      { key: "fallback_category_label", label: "Category label", placeholders: "(none)" },
      { key: "fallback_title", label: "Title", placeholders: "(none)" },
    ],
  },
];

function TemplatesTab() {
  const q = useOrg();
  const updateOrg = useUpdateOrg();
  const [form, setForm] = useState<PostTemplates | null>(null);
  const [note, setNote] = useState<{ ok: boolean; msg: string } | null>(null);

  // Prefill from the GET response until the operator starts editing.
  const templates: PostTemplates | null = form ?? (q.data ? { ...(q.data.settings?.post_templates ?? {}) } : null);

  function setField(key: PostTemplateKey, value: string) {
    setForm({ ...(templates ?? {}), [key]: value });
  }

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

  return (
    <Async q={q} rows={2}>
      {() =>
        templates && (
          <div className="space-y-4">
            <p className="max-w-2xl text-sm text-muted-foreground">
              These templates control the exact wording of generated post text. Keep the
              curly-brace placeholders intact — they&apos;re replaced with live values at post time.
            </p>
            {GROUPS.map((group) => (
              <Card key={group.title}>
                <CardHeader>
                  <CardTitle className="text-base font-semibold">{group.title}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {group.fields.map((field) => (
                    <div key={field.key} className="space-y-1.5">
                      <Label htmlFor={field.key}>{field.label}</Label>
                      <Textarea
                        id={field.key}
                        rows={3}
                        value={templates[field.key] ?? ""}
                        onChange={(e) => setField(field.key, e.target.value)}
                      />
                      <p className="text-xs text-muted-foreground">
                        Placeholders: <span className="font-mono">{field.placeholders}</span>
                      </p>
                    </div>
                  ))}
                </CardContent>
              </Card>
            ))}
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
