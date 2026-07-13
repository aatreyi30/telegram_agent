"use client";

import { useState } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { Delete02Icon } from "@hugeicons/core-free-icons";
import { Async } from "@/components/Async";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { useChannels } from "@/queries/queries";
import { useAddChannel, useDeleteChannel } from "@/queries/mutations";
import { OwnerOnly } from "../owner-guard";
import { Note } from "../note";

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

export default function ChannelsPage() {
  return (
    <OwnerOnly>
      <ChannelsTab />
    </OwnerOnly>
  );
}
