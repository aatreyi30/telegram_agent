"use client";

import { useState } from "react";
import { Async, Empty } from "@/components/Async";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PagedNav } from "@/components/PagedNav";
import { PageHeader } from "@/components/PageHeader";
import { PostPreview } from "@/components/PostPreview";
import { StatusPill } from "@/components/StatusPill";
import { MoneyBadge } from "@/components/MoneyBadge";
import { useDrafts } from "@/queries/queries";
import { useCreateDraft, useUpdateDraft, useDeleteDraft } from "@/queries/mutations";
import { postTypeLabel, merchantLabel } from "@/lib/format";
import type { DraftsResponse, EmojiPolicy, StrategyRationale } from "@/types/api";
import { Plus, Edit, Trash2 } from "lucide-react";

function DraftCard({ r, onEdit, onDelete }: { r: DraftsResponse["items"][number]; onEdit: (r: DraftsResponse["items"][number]) => void; onDelete: (id: number) => void }) {
  const rat: Partial<StrategyRationale> = r.rationale ?? {};
  const ep: Partial<EmojiPolicy> = rat.emoji_policy || r.emoji_policy || {};
  const hasRationale = rat.why_type || rat.target_window_ist?.why || ep.avoid?.length || rat.why_this_deal?.why;

  return (
    <Card className="overflow-hidden py-0">
      <CardHeader className="gap-0 border-b border-border bg-muted/20 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="font-mono text-[10px]">#{r.id}</Badge>
            <Badge variant="secondary" className="font-medium">{postTypeLabel(r.post_type)}</Badge>
            {r.merchant && <span className="text-xs text-muted-foreground">{merchantLabel(r.merchant)}</span>}
            <StatusPill status={r.status} />
            <MoneyBadge affiliateStatus={r.affiliate_status} merchant={r.merchant} />
          </div>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" onClick={() => onEdit(r)}>
              <Edit className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onDelete(r.id)}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 p-4">
        <PostPreview text={r.text} dense />
        {hasRationale && (
          <div className="space-y-1 text-xs text-muted-foreground">
            {rat.why_type && <div><span className="font-medium text-foreground">Why this post:</span> {rat.why_type}</div>}
            {rat.target_window_ist?.why && <div><span className="font-medium text-foreground">Best time:</span> {rat.target_window_ist.why}</div>}
            {!!ep.avoid?.length && (
              <div><span className="font-medium text-foreground">Emoji policy:</span> lead {(ep.lead || []).join(" ")}; stripped {(ep.avoid || []).join(" ")}</div>
            )}
            {rat.why_this_deal?.why && <div><span className="font-medium text-foreground">Why this deal:</span> {rat.why_this_deal.why}</div>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DraftForm({ draft, onClose }: { draft: DraftsResponse["items"][number] | null; onClose: () => void }) {
  const createDraft = useCreateDraft();
  const updateDraft = useUpdateDraft();
  const [text, setText] = useState(draft?.text || "");
  const [postType, setPostType] = useState(draft?.post_type || "manual");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (draft) {
      updateDraft.mutate({ id: draft.id, text, post_type: postType });
    } else {
      createDraft.mutate({ text, post_type: postType });
    }
    onClose();
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="text">Post Text</Label>
        <textarea
          id="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Enter your post text here..."
          required
          className="min-h-[200px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="postType">Post Type</Label>
        <Input
          id="postType"
          value={postType}
          onChange={(e) => setPostType(e.target.value)}
          placeholder="manual"
        />
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="submit">{draft ? "Update" : "Create"} Draft</Button>
      </div>
    </form>
  );
}

export default function DraftsPage() {
  const [page, setPage] = useState(1);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [editingDraft, setEditingDraft] = useState<DraftsResponse["items"][number] | null>(null);
  const q = useDrafts(page);
  const deleteDraft = useDeleteDraft();

  const handleCreate = () => {
    setEditingDraft(null);
    setIsDialogOpen(true);
  };

  const handleEdit = (draft: DraftsResponse["items"][number]) => {
    setEditingDraft(draft);
    setIsDialogOpen(true);
  };

  const handleDelete = (id: number) => {
    if (confirm("Are you sure you want to delete this draft?")) {
      deleteDraft.mutate(id);
    }
  };

  const handleClose = () => {
    setIsDialogOpen(false);
    setEditingDraft(null);
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Drafts"
        subtitle="Generated posts, shown exactly as they'll appear in Telegram. Each says why it fits the strategy and whether it earns."
        actions={
          <Button onClick={handleCreate}>
            <Plus className="h-4 w-4 mr-2" />
            Create draft
          </Button>
        }
      />
      <Dialog open={isDialogOpen} onClose={handleClose} title={editingDraft ? "Edit Draft" : "Create New Draft"}>
        <DraftForm draft={editingDraft} onClose={handleClose} />
      </Dialog>
      <Async q={q} rows={3}>
        {(d: DraftsResponse) =>
          d.items.length ? (
            <div className="space-y-4">
              <p className="text-xs text-muted-foreground">{d.total} draft{d.total === 1 ? "" : "s"} total</p>
              <div className="grid gap-4 lg:grid-cols-2">
                {d.items.map((r) => <DraftCard key={r.id} r={r} onEdit={handleEdit} onDelete={handleDelete} />)}
              </div>
              <PagedNav page={d.page} pages={d.pages} onPageChange={setPage} />
            </div>
          ) : (
            <Empty>No drafts yet. Use "Generate from today's deals" on the Overview or create a manual draft.</Empty>
          )
        }
      </Async>
    </div>
  );
}
