"use client";

import { useState } from "react";
import { Async } from "@/components/Async";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useOrg } from "@/queries/queries";
import { useUpdateOrg } from "@/queries/mutations";
import type { OrgSettings } from "@/types/api";
import { OwnerOnly } from "../owner-guard";
import { Note } from "../note";

function OrgTab() {
  const q = useOrg();
  const updateOrg = useUpdateOrg();
  const [form, setForm] = useState<{ name: string; settings: OrgSettings } | null>(null);
  const [note, setNote] = useState<{ ok: boolean; msg: string } | null>(null);
  const data = form || (q.data ? { name: q.data.name, settings: { ...q.data.settings } } : null);

  function set(k: "name", v: string) {
    setForm({ ...(data as { name: string; settings: OrgSettings }), [k]: v });
  }
  function setS(k: string, v: unknown) {
    setForm({ ...(data as { name: string; settings: OrgSettings }), settings: { ...(data?.settings || {}), [k]: v } });
  }
  async function save() {
    if (!data) return;
    setNote(null);
    try {
      await updateOrg.mutateAsync({ name: data.name, settings: data.settings });
      setNote({ ok: true, msg: "Organization saved." });
    } catch (e) {
      setNote({ ok: false, msg: (e as Error).message });
    }
  }

  return (
    <Async q={q} rows={1}>
      {() =>
        data && (
          <Card className="max-w-xl">
            <CardContent className="space-y-4 pt-4">
              <div className="space-y-1.5">
                <Label>Name</Label>
                <Input value={data.name || ""} onChange={(e) => set("name", e.target.value)} />
              </div>
              {q.data?.affiliate_provider && (
                <p className="text-xs text-muted-foreground">
                  Affiliate provider: <span className="font-medium text-foreground">{q.data.affiliate_provider}</span> — how product links are turned into earning links.
                </p>
              )}
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label>Amazon affiliate tag</Label>
                  <Input placeholder="yourtag-21" value={data.settings?.grabon_amazon_tag || ""} onChange={(e) => setS("grabon_amazon_tag", e.target.value)} />
                  <p className="text-xs text-muted-foreground">Added to Amazon links so purchases are credited to you.</p>
                </div>
                <div className="space-y-1.5">
                  <Label>Flipkart params</Label>
                  <Input placeholder="affid=xxxxx&affExtParam1=..." value={data.settings?.grabon_flipkart_params || ""} onChange={(e) => setS("grabon_flipkart_params", e.target.value)} />
                  <p className="text-xs text-muted-foreground">Flipkart affiliate query string appended to its links.</p>
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>Myntra deeplink</Label>
                <Input placeholder="https://ww44.affinity.net/sssweb?enk=...&d=<encoded_deal>" value={data.settings?.grabon_myntra_deeplink || ""} onChange={(e) => setS("grabon_myntra_deeplink", e.target.value)} />
                <p className="text-xs text-muted-foreground">Myntra affiliate template — the product link is URL-encoded and dropped in where <code>&lt;encoded_deal&gt;</code> appears.</p>
              </div>
              <div className="space-y-1.5">
                <Label>Shortener URL</Label>
                <Input placeholder="https://grbn.in" value={data.settings?.grabon_shortener_url || ""} onChange={(e) => setS("grabon_shortener_url", e.target.value)} />
                <p className="text-xs text-muted-foreground">Base of your short-link service — every posted link is shortened through it for click tracking.</p>
              </div>
              <div className="space-y-1.5">
                <Label>Preferred categories (comma-separated)</Label>
                <Input
                  placeholder="electronics-and-gadgets, fashion-and-lifestyle, …"
                  value={(data.settings?.preferred_categories || []).join(", ")}
                  onChange={(e) => setS("preferred_categories",
                    e.target.value.split(",").map((x: string) => x.trim()).filter(Boolean))}
                />
                <p className="text-xs text-muted-foreground">The agent schedules these categories first at peak-views hours; the rest fill remaining slots by deal quality.</p>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={!!data.settings?.grabon_shorten_all}
                  onChange={(e) => setS("grabon_shorten_all", e.target.checked)} />
                Shorten every link (even merchants with no affiliate rule)
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={data.settings?.auto_discover_competitors !== false}
                  onChange={(e) => setS("auto_discover_competitors", e.target.checked)} />
                Auto-discover new competitor channels
              </label>
              <p className="text-xs text-muted-foreground">
                When off, the daily discovery job stops adding new competitors automatically —
                existing ones (and their monitoring toggle in Settings &gt; Competitors) are unaffected.
              </p>
              {note && <Note {...note} />}
              <Button onClick={save}>Save organization</Button>
            </CardContent>
          </Card>
        )
      }
    </Async>
  );
}

export default function OrgPage() {
  return (
    <OwnerOnly>
      <OrgTab />
    </OwnerOnly>
  );
}
