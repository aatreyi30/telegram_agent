"use client";

import { useState } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { Delete02Icon, UserAdd01Icon } from "@hugeicons/core-free-icons";
import { Async } from "@/components/Async";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { useUsers } from "@/queries/queries";
import { useCreateUser, useDeleteUser, useUpdateUserRole } from "@/queries/mutations";
import { useAuth } from "@/providers/auth";
import { OwnerOnly } from "../owner-guard";

function UsersTab() {
  const q = useUsers();
  const { user: me } = useAuth();
  const createUser = useCreateUser();
  const deleteUser = useDeleteUser();
  const updateRole = useUpdateUserRole();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", email: "", password: "", role: "editor" });
  const [note, setNote] = useState<string | null>(null);
  const canCreate = f.name.trim() && f.email.trim() && f.password.length >= 6;

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
  async function remove(id: number, name: string) {
    if (!confirm(`Remove ${name}? They'll lose access immediately.`)) return;
    setNote(null);
    try {
      await deleteUser.mutateAsync(id);
    } catch (e) {
      setNote((e as Error).message);
    }
  }
  async function changeRole(id: number, role: string) {
    setNote(null);
    try {
      await updateRole.mutateAsync({ id, role });
    } catch (e) {
      setNote((e as Error).message);
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        {note && !open ? <p className="text-sm text-destructive">{note}</p> : <span />}
        <Button size="sm" onClick={() => { setNote(null); setOpen(true); }}><HugeiconsIcon icon={UserAdd01Icon} size={16} /> Add user</Button>
      </CardHeader>
      <CardContent className="p-0">
        <Async q={q} rows={2}>
          {(users) => (
            <Table>
              <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Email</TableHead><TableHead>Role</TableHead><TableHead>Last login</TableHead><TableHead></TableHead></TableRow></TableHeader>
              <TableBody>
                {users.map((u) => {
                  const isSelf = u.id === me?.id;
                  return (
                  <TableRow key={u.id}>
                    <TableCell className="font-medium">{u.name}{isSelf && <span className="ml-1.5 text-xs text-muted-foreground">(you)</span>}</TableCell>
                    <TableCell>{u.email}</TableCell>
                    <TableCell>
                      <Select value={u.role} onValueChange={(role) => changeRole(u.id, role as string)} disabled={isSelf}>
                        <SelectTrigger className="h-8 w-28" title={isSelf ? "You can't change your own role" : undefined}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="owner">Owner</SelectItem>
                          <SelectItem value="editor">Editor</SelectItem>
                          <SelectItem value="viewer">Viewer</SelectItem>
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{u.last_login_at ? u.last_login_at.slice(0, 10) : "—"}</TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-destructive hover:bg-destructive/10 hover:text-destructive disabled:opacity-30"
                        disabled={isSelf}
                        title={isSelf ? "You can't remove yourself" : "Remove user"}
                        onClick={() => remove(u.id, u.name)}
                      >
                        <HugeiconsIcon icon={Delete02Icon} size={16} />
                      </Button>
                    </TableCell>
                  </TableRow>
                  );
                })}
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
          <Button className="w-full" onClick={create} disabled={!canCreate || createUser.isPending}>
            {createUser.isPending ? "Creating…" : "Create user"}
          </Button>
        </div>
      </Dialog>
    </Card>
  );
}

export default function UsersPage() {
  return (
    <OwnerOnly>
      <UsersTab />
    </OwnerOnly>
  );
}
