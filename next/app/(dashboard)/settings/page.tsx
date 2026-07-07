"use client";

import { useState } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  Building01Icon, Delete02Icon, Satellite01Icon, UserAdd01Icon, UserGroupIcon, UserIcon,
} from "@hugeicons/core-free-icons";
import { Async } from "@/components/Async";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { useAuth } from "@/providers/auth";
import { useChannels, useOrg, useUsers } from "@/queries/queries";
import {
  useAddChannel, useChangePassword, useCreateUser, useDeleteChannel,
  useDeleteUser, useUpdateOrg, useUpdateUserRole,
} from "@/queries/mutations";
import type { OrgSettings } from "@/types/api";

function Note({ ok, msg }: { ok: boolean; msg: string }) {
  return <p className={ok ? "text-sm text-success" : "text-sm text-destructive"}>{msg}</p>;
}

function ProfileTab() {
  const { user } = useAuth();
  const [oldp, setOld] = useState("");
  const [newp, setNew] = useState("");
  const [note, setNote] = useState<{ ok: boolean; msg: string } | null>(null);
  const changePassword = useChangePassword();

  async function save() {
    setNote(null);
    try {
      await changePassword.mutateAsync({ old_password: oldp, new_password: newp });
      setNote({ ok: true, msg: "Password updated." });
      setOld(""); setNew("");
    } catch (e) {
      setNote({ ok: false, msg: (e as Error).message });
    }
  }

  return (
    <Card className="max-w-md">
      <CardContent className="space-y-4 pt-4">
        <div className="text-sm text-muted-foreground">
          {user?.name} · {user?.email} · <span className="capitalize">{user?.role}</span>
        </div>
        <div className="space-y-1.5">
          <Label>Current password</Label>
          <Input type="password" value={oldp} onChange={(e) => setOld(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label>New password</Label>
          <Input type="password" value={newp} onChange={(e) => setNew(e.target.value)} />
        </div>
        {note && <Note {...note} />}
        <Button onClick={save} disabled={!oldp || newp.length < 6}>Change password</Button>
      </CardContent>
    </Card>
  );
}

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

function UsersTab() {
  const q = useUsers();
  const createUser = useCreateUser();
  const deleteUser = useDeleteUser();
  const updateRole = useUpdateUserRole();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", email: "", password: "", role: "editor" });
  const [note, setNote] = useState<string | null>(null);

  async function create() {
    setNote(null);
    try {
      await createUser.mutateAsync(f);
      setOpen(false);
      setF({ name: "", email: "", password: "", role: "editor" });
    } catch (e) {
      setNote((e as Error).message);
    }
  }
  async function remove(id: number) {
    try {
      await deleteUser.mutateAsync(id);
    } catch (e) {
      setNote((e as Error).message);
    }
  }
  async function changeRole(id: number, role: string) {
    await updateRole.mutateAsync({ id, role });
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-end">
        <Button size="sm" onClick={() => setOpen(true)}><HugeiconsIcon icon={UserAdd01Icon} size={16} /> Add user</Button>
      </CardHeader>
      <CardContent className="p-0">
        <Async q={q} rows={2}>
          {(users) => (
            <Table>
              <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Email</TableHead><TableHead>Role</TableHead><TableHead>Last login</TableHead><TableHead></TableHead></TableRow></TableHeader>
              <TableBody>
                {users.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell className="font-medium">{u.name}</TableCell>
                    <TableCell>{u.email}</TableCell>
                    <TableCell>
                      <Select value={u.role} onValueChange={(role) => changeRole(u.id, role as string)}>
                        <SelectTrigger className="h-8 w-28">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="owner">owner</SelectItem>
                          <SelectItem value="editor">editor</SelectItem>
                          <SelectItem value="viewer">viewer</SelectItem>
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{u.last_login_at ? u.last_login_at.slice(0, 10) : "—"}</TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                        onClick={() => remove(u.id)}
                      >
                        <HugeiconsIcon icon={Delete02Icon} size={16} />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Async>
      </CardContent>

      <Dialog open={open} onClose={() => setOpen(false)} title="Add user">
        <div className="space-y-3">
          <div className="space-y-1.5"><Label>Name</Label>
            <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
          <div className="space-y-1.5"><Label>Email</Label>
            <Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
          <div className="space-y-1.5"><Label>Password (6+ chars)</Label>
            <Input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
          <div className="space-y-1.5"><Label>Role</Label>
            <Select value={f.role} onValueChange={(role) => setF({ ...f, role: role as string })}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="owner">owner</SelectItem>
                <SelectItem value="editor">editor</SelectItem>
                <SelectItem value="viewer">viewer</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {note && <p className="text-sm text-destructive">{note}</p>}
          <Button className="w-full" onClick={create}>Create user</Button>
        </div>
      </Dialog>
    </Card>
  );
}

function ChannelsTab() {
  const q = useChannels();
  const addChannel = useAddChannel();
  const deleteChannel = useDeleteChannel();
  const [handle, setHandle] = useState("");
  const [note, setNote] = useState<{ ok: boolean; msg: string } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; username: string | null; posts: number } | null>(null);

  async function add() {
    setNote(null);
    try {
      await addChannel.mutateAsync({ username: handle.trim(), kind: "owned" });
      setHandle("");
      setNote({ ok: true, msg: "Channel added. Connect Telegram (see below), then run a sync to start collecting." });
    } catch (e) {
      setNote({ ok: false, msg: (e as Error).message });
    }
  }
  async function confirmDelete() {
    if (!deleteTarget) return;
    try {
      await deleteChannel.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (e) {
      setNote({ ok: false, msg: (e as Error).message });
      setDeleteTarget(null);
    }
  }

  return (
    <div className="space-y-4">
      <Card className="max-w-xl">
        <CardHeader><CardTitle className="text-base">Add your Telegram channel</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-end gap-2">
            <div className="flex-1 space-y-1.5">
              <Label>Channel @username or t.me link</Label>
              <Input placeholder="@YourDealsChannel" value={handle}
                onChange={(e) => setHandle(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handle.trim() && add()} />
            </div>
            <Button onClick={add} disabled={!handle.trim()}>Add channel</Button>
          </div>
          {note && <Note {...note} />}
          <p className="text-xs text-muted-foreground">
            A new channel starts as <b>pending</b>. Collecting its posts and stats requires a
            Telegram account that administers it — set <code>TELEGRAM_API_ID / HASH / PHONE</code>
            for that account and sign in once, then run a sync. The channel flips to <b>active</b>
            after its first successful collection.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Your channels</CardTitle></CardHeader>
        <CardContent className="p-0">
          <Async q={q} rows={2}>
            {(channels) =>
              channels.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">No channels yet — add one above.</p>
              ) : (
                <Table>
                  <TableHeader><TableRow><TableHead>Channel</TableHead><TableHead>Type</TableHead><TableHead>Status</TableHead><TableHead>Posts</TableHead><TableHead></TableHead></TableRow></TableHeader>
                  <TableBody>
                    {channels.map((c) => (
                      <TableRow key={c.id}>
                        <TableCell className="font-medium">{c.username ? `@${c.username}` : c.title || `#${c.id}`}</TableCell>
                        <TableCell className="capitalize text-muted-foreground">{c.kind}</TableCell>
                        <TableCell>
                          <Badge className={c.status === "active"
                            ? "bg-success/15 text-success"
                            : "bg-muted text-muted-foreground"}>{c.status}</Badge>
                        </TableCell>
                        <TableCell>{c.posts.toLocaleString()}</TableCell>
                        <TableCell>
                          <Button variant="ghost" size="icon" onClick={() => setDeleteTarget(c)}>
                            <HugeiconsIcon icon={Delete02Icon} size={16} className="text-destructive" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )
            }
          </Async>
        </CardContent>

        <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete channel">
          <div className="space-y-3">
            <p className="text-sm">
              {deleteTarget && (deleteTarget.posts > 0
                ? `Delete @${deleteTarget.username} and its ${deleteTarget.posts} posts + all derived data? This cannot be undone.`
                : `Remove @${deleteTarget.username}?`)}
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(null)}>Cancel</Button>
              <Button variant="destructive" size="sm" onClick={confirmDelete}>Delete</Button>
            </div>
          </div>
        </Dialog>
      </Card>
    </div>
  );
}

const SETTINGS_NAV = [
  { key: "profile", label: "Profile", icon: UserIcon, description: "Your account and password.", ownerOnly: false },
  { key: "channels", label: "Channels", icon: Satellite01Icon, description: "The Telegram channels you own and track.", ownerOnly: true },
  { key: "org", label: "Organization", icon: Building01Icon, description: "Company details and affiliate link settings.", ownerOnly: true },
  { key: "users", label: "Users", icon: UserGroupIcon, description: "Teammates and their access level.", ownerOnly: true },
] as const;

export default function SettingsPage() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const items = SETTINGS_NAV.filter((i) => !i.ownerOnly || isOwner);
  const [tab, setTab] = useState<string>("profile");
  const active = items.find((i) => i.key === tab) ?? items[0];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">Your profile, channels, the organization, and users.</p>
      </div>
      <div className="flex flex-col gap-8 md:flex-row">
        <nav className="flex shrink-0 gap-1 overflow-x-auto pb-1 md:w-52 md:flex-col md:overflow-visible md:pb-0">
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setTab(item.key)}
              className={cn(
                "flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors",
                active.key === item.key
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
              )}
            >
              <HugeiconsIcon icon={item.icon} size={17} className="shrink-0" />
              {item.label}
            </button>
          ))}
        </nav>
        <div className="min-w-0 flex-1 space-y-4">
          <div>
            <h2 className="text-lg font-semibold">{active.label}</h2>
            <p className="text-sm text-muted-foreground">{active.description}</p>
          </div>
          {active.key === "profile" && <ProfileTab />}
          {active.key === "channels" && isOwner && <ChannelsTab />}
          {active.key === "org" && isOwner && <OrgTab />}
          {active.key === "users" && isOwner && <UsersTab />}
        </div>
      </div>
    </div>
  );
}
