"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/providers/auth";
import { useChangePassword } from "@/queries/mutations";
import { Note } from "../note";

export default function ProfilePage() {
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
