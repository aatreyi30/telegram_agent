"use client";

import { useState } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { UserGroupIcon, Edit03Icon, Delete02Icon } from "@hugeicons/core-free-icons";
import { Async } from "@/components/Async";
import { CategoryBadge } from "@/components/CategoryBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCompetitors } from "@/queries/queries";
import { useCreateCompetitor, useDeleteCompetitor, useUpdateCompetitor } from "@/queries/mutations";
import type { CompetitorRow } from "@/types/api";
import { OwnerOnly } from "../owner-guard";

type Category = "platform" | "channel";

// Shared Direct/Indirect classification control -- used by both the add and
// edit dialogs so the two never drift apart.
function CategorySelector({ value, onChange }: { value: Category; onChange: (v: Category) => void }) {
  return (
    <Tabs value={value} onValueChange={(v) => onChange(v as Category)}>
      <TabsList>
        <TabsTrigger value="platform">Direct</TabsTrigger>
        <TabsTrigger value="channel">Indirect</TabsTrigger>
      </TabsList>
    </Tabs>
  );
}

function CompetitorsTab() {
  const q = useCompetitors();
  const createCompetitor = useCreateCompetitor();
  const updateCompetitor = useUpdateCompetitor();
  const deleteCompetitor = useDeleteCompetitor();

  // Add dialog
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [category, setCategory] = useState<Category>("platform");
  const [note, setNote] = useState<string | null>(null);

  // Edit dialog
  const [editTarget, setEditTarget] = useState<CompetitorRow | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editCategory, setEditCategory] = useState<Category>("platform");
  const [editNote, setEditNote] = useState<string | null>(null);

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<CompetitorRow | null>(null);
  const [deleteNote, setDeleteNote] = useState<string | null>(null);

  function closeDialog() {
    setOpen(false);
    setNote(null);
    setUsername("");
    setCategory("platform");
  }

  async function add() {
    setNote(null);
    try {
      await createCompetitor.mutateAsync({ username: username.trim(), category });
      closeDialog();
    } catch (e) {
      setNote((e as Error)?.message || "Failed to add competitor.");
    }
  }

  function openEdit(c: CompetitorRow) {
    setEditTarget(c);
    setEditTitle(c.title || "");
    setEditCategory((c.category as Category) || "platform");
    setEditNote(null);
  }

  async function saveEdit() {
    if (!editTarget) return;
    setEditNote(null);
    try {
      await updateCompetitor.mutateAsync({ id: editTarget.id, category: editCategory, title: editTitle });
      setEditTarget(null);
    } catch (e) {
      setEditNote((e as Error)?.message || "Failed to update competitor.");
    }
  }

  async function toggleMonitoring(c: CompetitorRow) {
    try {
      await updateCompetitor.mutateAsync({ id: c.id, monitoring_enabled: !c.monitoring_enabled });
    } catch {
      // best-effort — the row just won't flip; no separate error surface for this control
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    try {
      await deleteCompetitor.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (e) {
      setDeleteNote((e as Error)?.message || "Failed to delete competitor.");
      setDeleteTarget(null);
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-end">
        <Button size="sm" onClick={() => setOpen(true)}><HugeiconsIcon icon={UserGroupIcon} size={16} /> Add competitor</Button>
      </CardHeader>
      <CardContent className="p-0">
        <Async q={q} rows={2}>
          {(data) => {
            const rows = data.competitors ?? [];
            return rows.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">No competitors yet — add one above.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Competitor</TableHead>
                    <TableHead>Title</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead>Posts</TableHead>
                    <TableHead>Monitored</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell className="font-medium">{c.username ? `@${c.username}` : "—"}</TableCell>
                      <TableCell className="text-muted-foreground">{c.title || "—"}</TableCell>
                      <TableCell><CategoryBadge category={c.category ?? undefined} /></TableCell>
                      <TableCell>{(c.posts ?? 0).toLocaleString()}</TableCell>
                      <TableCell>
                        <Button
                          variant={c.monitoring_enabled ? "secondary" : "outline"}
                          size="sm"
                          onClick={() => toggleMonitoring(c)}
                          disabled={updateCompetitor.isPending}
                          aria-pressed={c.monitoring_enabled}
                        >
                          {c.monitoring_enabled ? "On" : "Off"}
                        </Button>
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="icon" onClick={() => openEdit(c)}>
                            <HugeiconsIcon icon={Edit03Icon} size={16} />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => setDeleteTarget(c)}>
                            <HugeiconsIcon icon={Delete02Icon} size={16} className="text-destructive" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            );
          }}
        </Async>
      </CardContent>

      <Dialog open={open} onClose={closeDialog} title="Add competitor">
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Telegram @username</Label>
            <Input
              placeholder="@RivalDealsChannel"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && username.trim() && add()}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Classification</Label>
            <CategorySelector value={category} onChange={setCategory} />
          </div>
          {note && <p className="text-sm text-destructive">{note}</p>}
          <Button className="w-full" onClick={add} disabled={!username.trim() || createCompetitor.isPending}>
            {createCompetitor.isPending ? "Adding…" : "Add competitor"}
          </Button>
        </div>
      </Dialog>

      <Dialog open={!!editTarget} onClose={() => setEditTarget(null)} title="Edit competitor">
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Telegram @username</Label>
            <Input value={editTarget?.username ? `@${editTarget.username}` : ""} disabled readOnly />
          </div>
          <div className="space-y-1.5">
            <Label>Title</Label>
            <Input
              placeholder="Display title"
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Classification</Label>
            <CategorySelector value={editCategory} onChange={setEditCategory} />
          </div>
          {editNote && <p className="text-sm text-destructive">{editNote}</p>}
          <Button className="w-full" onClick={saveEdit} disabled={updateCompetitor.isPending}>
            {updateCompetitor.isPending ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </Dialog>

      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete competitor">
        <div className="space-y-3">
          <p className="text-sm">
            {deleteTarget && ((deleteTarget.posts ?? 0) > 0
              ? `Delete @${deleteTarget.username} and its ${deleteTarget.posts} posts + all derived competitor data? This cannot be undone.`
              : `Remove @${deleteTarget.username}?`)}
          </p>
          {deleteNote && <p className="text-sm text-destructive">{deleteNote}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button variant="destructive" size="sm" onClick={confirmDelete}>Delete</Button>
          </div>
        </div>
      </Dialog>
    </Card>
  );
}

export default function CompetitorsPage() {
  return (
    <OwnerOnly>
      <CompetitorsTab />
    </OwnerOnly>
  );
}
