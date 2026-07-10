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
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label>Amazon affiliate tag</Label>
                  <Input value={data.settings?.grabon_amazon_tag || ""} onChange={(e) => setS("grabon_amazon_tag", e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label>Flipkart params</Label>
                  <Input value={data.settings?.grabon_flipkart_params || ""} onChange={(e) => setS("grabon_flipkart_params", e.target.value)} />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>Shortener URL</Label>
                <Input value={data.settings?.grabon_shortener_url || ""} onChange={(e) => setS("grabon_shortener_url", e.target.value)} />
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
