import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, UserPlus } from "lucide-react";
import { PageHeader } from "@/components/AppLayout";
import { Async } from "@/components/Async";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Badge, Input, Label, Select } from "@/components/ui/primitives";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/services/api";
import { useAuth } from "@/providers/auth";

function Note({ ok, msg }: { ok: boolean; msg: string }) {
  return <p className={ok ? "text-sm text-success" : "text-sm text-destructive"}>{msg}</p>;
}

function ProfileTab() {
  const { user } = useAuth();
  const [oldp, setOld] = useState("");
  const [newp, setNew] = useState("");
  const [note, setNote] = useState<{ ok: boolean; msg: string } | null>(null);

  async function save() {
    setNote(null);
    try {
      await api.post("/api/auth/change-password", { old_password: oldp, new_password: newp });
      setNote({ ok: true, msg: "Password updated." });
      setOld(""); setNew("");
    } catch (e) {
      setNote({ ok: false, msg: (e as Error).message });
    }
  }

  return (
    <Card className="max-w-md">
      <CardHeader><CardTitle className="text-base">Your profile</CardTitle></CardHeader>
      <CardContent className="space-y-4">
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
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["org"], queryFn: () => api.get<any>("/api/org") });
  const [form, setForm] = useState<any>(null);
  const [note, setNote] = useState<{ ok: boolean; msg: string } | null>(null);
  const data = form || (q.data ? { name: q.data.name, settings: { ...q.data.settings } } : null);

  function set(k: string, v: any) {
    setForm({ ...(data || {}), [k]: v });
  }
  function setS(k: string, v: any) {
    setForm({ ...(data || {}), settings: { ...(data?.settings || {}), [k]: v } });
  }
  async function save() {
    setNote(null);
    try {
      await api.patch("/api/org", { name: data.name, settings: data.settings });
      qc.invalidateQueries({ queryKey: ["org"] });
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
            <CardHeader><CardTitle className="text-base">Organization</CardTitle></CardHeader>
            <CardContent className="space-y-4">
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
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["users"], queryFn: () => api.get<any[]>("/api/users") });
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", email: "", password: "", role: "editor" });
  const [note, setNote] = useState<string | null>(null);

  async function create() {
    setNote(null);
    try {
      await api.post("/api/users", f);
      qc.invalidateQueries({ queryKey: ["users"] });
      setOpen(false);
      setF({ name: "", email: "", password: "", role: "editor" });
    } catch (e) {
      setNote((e as Error).message);
    }
  }
  async function remove(id: number) {
    try {
      await api.del(`/api/users/${id}`);
      qc.invalidateQueries({ queryKey: ["users"] });
    } catch (e) {
      alert((e as Error).message);
    }
  }
  async function changeRole(id: number, role: string) {
    await api.patch(`/api/users/${id}`, { role });
    qc.invalidateQueries({ queryKey: ["users"] });
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="text-base">Users</CardTitle>
        <Button size="sm" onClick={() => setOpen(true)}><UserPlus size={16} /> Add user</Button>
      </CardHeader>
      <CardContent className="p-0">
        <Async q={q} rows={2}>
          {(users) => (
            <Table>
              <THead><TR><TH>Name</TH><TH>Email</TH><TH>Role</TH><TH>Last login</TH><TH></TH></TR></THead>
              <TBody>
                {users.map((u) => (
                  <TR key={u.id}>
                    <TD className="font-medium">{u.name}</TD>
                    <TD>{u.email}</TD>
                    <TD>
                      <Select value={u.role} onChange={(e) => changeRole(u.id, e.target.value)} className="h-8 w-28">
                        <option value="owner">owner</option>
                        <option value="editor">editor</option>
                        <option value="viewer">viewer</option>
                      </Select>
                    </TD>
                    <TD className="text-muted-foreground">{u.last_login_at ? u.last_login_at.slice(0, 10) : "—"}</TD>
                    <TD>
                      <Button variant="ghost" size="icon" onClick={() => remove(u.id)}>
                        <Trash2 size={16} className="text-destructive" />
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
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
            <Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              <option value="owner">owner</option>
              <option value="editor">editor</option>
              <option value="viewer">viewer</option>
            </Select></div>
          {note && <p className="text-sm text-destructive">{note}</p>}
          <Button className="w-full" onClick={create}>Create user</Button>
        </div>
      </Dialog>
    </Card>
  );
}

export function Settings() {
  const { user } = useAuth();
  const [tab, setTab] = useState("profile");
  const isOwner = user?.role === "owner";
  return (
    <div>
      <PageHeader title="Settings" sub="Your profile, the organization, and users." />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="profile">Profile</TabsTrigger>
          {isOwner && <TabsTrigger value="org">Organization</TabsTrigger>}
          {isOwner && <TabsTrigger value="users">Users</TabsTrigger>}
        </TabsList>
        <TabsContent value="profile"><ProfileTab /></TabsContent>
        {isOwner && <TabsContent value="org"><OrgTab /></TabsContent>}
        {isOwner && <TabsContent value="users"><UsersTab /></TabsContent>}
      </Tabs>
    </div>
  );
}
