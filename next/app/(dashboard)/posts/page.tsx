"use client";

import { Suspense, useState } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { HugeiconsIcon } from "@hugeicons/react";
import { Clock01Icon, Sent02Icon } from "@hugeicons/core-free-icons";
import { Async, Empty } from "@/components/Async";
import { AiBadge } from "@/components/AiBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PageHeader } from "@/components/PageHeader";
import { PagedNav } from "@/components/PagedNav";
import { PostPreview } from "@/components/PostPreview";
import { StatusPill, StatusCounts } from "@/components/StatusPill";
import { MoneyBadge } from "@/components/MoneyBadge";
import { ReasoningPanel, hasRationale } from "@/components/ReasoningPanel";
import { useDrafts, useQueue } from "@/queries/queries";
import { useCreateDraft, useUpdateDraft, useDeleteDraft } from "@/queries/mutations";
import { postTypeLabel, merchantLabel, istDateTime, relative } from "@/lib/format";
import type { DraftItem, QueueItem, StrategyRationale } from "@/types/api";
import { Plus, Edit, Trash2 } from "lucide-react";

const TABS = [
  { value: "draft", label: "Draft" },
  { value: "queued", label: "Queued" },
  { value: "published", label: "Published" },
  { value: "blocked", label: "Blocked" },
  { value: "all", label: "All" },
] as const;

/** Normalized shape both DraftItem and QueueItem map onto, so one row/sheet renderer
 * handles both sources instead of forking the whole page in two. */
interface Row {
  id: number;
  source: "draft" | "queue";
  post_type: string | null;
  merchant: string | null;
  affiliate_status: string | null;
  text: string | null;
  rationale: StrategyRationale | null;
  status: string;
  when: string | null;
  whenLabel: string;
  overdue?: boolean;
  channel?: string | null;
  attempts?: string;
  note?: string;
  raw: DraftItem | QueueItem;
}

function fromDraft(r: DraftItem): Row {
  return {
    id: r.id, source: "draft", post_type: r.post_type, merchant: r.merchant,
    affiliate_status: r.affiliate_status, text: r.text, rationale: r.rationale,
    status: r.status, when: r.generated_at, whenLabel: "Generated", raw: r,
  };
}

function fromQueue(r: QueueItem): Row {
  return {
    id: r.id, source: "queue", post_type: r.post_type, merchant: r.merchant,
    affiliate_status: r.affiliate_status, text: r.text, rationale: r.rationale,
    status: r.status, when: r.scheduled_at, whenLabel: "Fires", overdue: r.overdue,
    channel: r.channel, attempts: r.attempts, note: r.note, raw: r,
  };
}

function firstLine(text?: string | null): string {
  if (!text) return "";
  const line = text.split("\n").find((l) => l.trim());
  return (line || "").replace(/\*\*|__|`/g, "").trim();
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <span className="shrink-0 text-xs text-muted-foreground">{label}</span>
      <span className="text-right text-sm">{children}</span>
    </div>
  );
}

/** Click-to-pop reasoning, right next to the row — the fast path. The Sheet still
 * shows the full ReasoningPanel too, for when you want the whole detail view open. */
function ReasoningTrigger({ rationale }: { rationale: StrategyRationale | null }) {
  if (!hasRationale(rationale)) return null;
  return (
    <Popover
      align="end"
      className="w-80 border-violet-400/30 bg-gradient-to-b from-violet-500/[0.06] to-popover"
      trigger={
        <button type="button" onClick={(e) => e.stopPropagation()}>
          <AiBadge label="Why?" />
        </button>
      }
    >
      <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-violet-600 dark:text-violet-300">
        <AiBadge label="Reasoning" />
      </div>
      <ReasoningPanel rationale={rationale} />
    </Popover>
  );
}

function DraftForm({ draft, onClose }: { draft: DraftItem | null; onClose: () => void }) {
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
        <Input id="postType" value={postType} onChange={(e) => setPostType(e.target.value)} placeholder="manual" />
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="submit">{draft ? "Update" : "Create"} Draft</Button>
      </div>
    </form>
  );
}

function PostsInner() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const tab = sp.get("status") ?? "draft";
  const page = Math.max(1, Number(sp.get("page") || 1));
  const date = sp.get("date") || "";
  const type = sp.get("type") || "";
  const sort = sp.get("sort") || "soonest";
  const [active, setActive] = useState<Row | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [editingDraft, setEditingDraft] = useState<DraftItem | null>(null);
  const deleteDraft = useDeleteDraft();

  const isDraftTab = tab === "draft";
  const draftsQ = useDrafts(page);
  const queueQ = useQueue({ page, date, type, status: (tab === "draft" || tab === "all") ? "" : tab, sort }, 15);

  function update(patch: Record<string, string>, keepPage = false) {
    const p = new URLSearchParams(sp.toString());
    for (const [k, v] of Object.entries(patch)) v ? p.set(k, v) : p.delete(k);
    if (!keepPage) p.delete("page");
    router.replace(p.toString() ? `${pathname}?${p}` : pathname, { scroll: false });
  }
  const hasFilters = !!(date || type) || sort !== "soonest";

  const handleEdit = (r: DraftItem) => { setEditingDraft(r); setIsDialogOpen(true); };
  const handleCreate = () => { setEditingDraft(null); setIsDialogOpen(true); };
  const handleDelete = (id: number) => {
    if (confirm("Are you sure you want to delete this draft?")) deleteDraft.mutate(id);
  };
  const handleClose = () => { setIsDialogOpen(false); setEditingDraft(null); };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Posts"
        subtitle="Every post the agent has written or scheduled — draft, queued, published or blocked — in one place."
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

      {/* status tabs */}
      <div className="flex rounded-lg border bg-card p-0.5 w-fit">
        {TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            onClick={() => update({ status: t.value }, false)}
            className={
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors " +
              (tab === t.value
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground")
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* filters — only meaningful for queue-backed tabs */}
      {!isDraftTab && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="date"
            value={date}
            onChange={(e) => update({ date: e.target.value })}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-xs"
            aria-label="Filter by date"
          />
          <Select value={type || "all"} onValueChange={(v) => update({ type: v === "all" ? "" : v })}>
            <SelectTrigger className="h-9 w-[130px]" aria-label="Filter by type"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All types</SelectItem>
              <SelectItem value="single">Single deal</SelectItem>
              <SelectItem value="loot">Loot board</SelectItem>
            </SelectContent>
          </Select>
          <Select value={sort} onValueChange={(v) => update({ sort: v })}>
            <SelectTrigger className="h-9 w-[140px]" aria-label="Sort by date"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="soonest">Soonest first</SelectItem>
              <SelectItem value="latest">Latest first</SelectItem>
            </SelectContent>
          </Select>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={() => update({ date: "", type: "", sort: "" })}>
              Clear
            </Button>
          )}
        </div>
      )}

      {isDraftTab ? (
        <Async q={draftsQ} rows={3}>
          {(d) => {
            const rows = d.items.map(fromDraft);
            return rows.length ? (
              <>
                <p className="text-xs text-muted-foreground">{d.total} draft{d.total === 1 ? "" : "s"} total</p>
                <PostList rows={rows} onOpen={setActive} onEdit={(r) => handleEdit(r.raw as DraftItem)} onDelete={handleDelete} />
                <PagedNav page={d.page} pages={d.pages} onPageChange={(n) => update({ page: String(n) }, true)} />
              </>
            ) : (
              <Empty>No drafts yet. The agent creates these automatically from today's plan, or click "Create draft" above.</Empty>
            );
          }}
        </Async>
      ) : (
        <Async q={queueQ} rows={3}>
          {(d) => {
            const rows = d.items.map(fromQueue);
            return (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusCounts counts={d.counts} />
                  {Object.keys(d.counts || {}).length === 0 && (
                    <span className="text-sm text-muted-foreground">Nothing here.</span>
                  )}
                  <span className="ml-auto text-xs text-muted-foreground">{d.total} total</span>
                </div>
                {rows.length ? (
                  <>
                    <PostList rows={rows} onOpen={setActive} />
                    <PagedNav page={d.page} pages={d.pages} onPageChange={(n) => update({ page: String(n) }, true)} />
                  </>
                ) : (
                  <Empty>
                    {hasFilters ? "No posts match these filters. Adjust or clear them."
                      : "Nothing here yet. The agent fills each slot from your daily plan a few minutes before it fires."}
                  </Empty>
                )}
              </div>
            );
          }}
        </Async>
      )}

      {/* row detail drawer */}
      <Sheet open={!!active} onOpenChange={(o) => !o && setActive(null)}>
        <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-md">
          {active && (
            <>
              <SheetHeader className="border-b">
                <SheetTitle className="flex items-center gap-2">
                  <HugeiconsIcon icon={Sent02Icon} className="h-4 w-4 text-primary" />
                  {postTypeLabel(active.post_type)}
                  {active.merchant && <span className="text-muted-foreground">· {merchantLabel(active.merchant)}</span>}
                </SheetTitle>
              </SheetHeader>
              <div className="space-y-4 p-4">
                {active.text ? <PostPreview text={active.text} /> : (
                  <p className="text-sm text-muted-foreground">This item has no rendered post yet.</p>
                )}
                {hasRationale(active.rationale) && (
                  <div className="rounded-lg border border-violet-400/30 bg-gradient-to-b from-violet-500/[0.06] to-transparent p-3">
                    <div className="mb-2"><AiBadge label="Reasoning" /></div>
                    <ReasoningPanel rationale={active.rationale} />
                  </div>
                )}
                <div className="rounded-lg border">
                  <div className="divide-y divide-border px-3">
                    {active.when && (
                      <DetailRow label={active.whenLabel}>
                        <span className="font-medium">{relative(active.when)}</span> · {istDateTime(active.when)}
                      </DetailRow>
                    )}
                    <DetailRow label="Status">
                      <span className="inline-flex items-center gap-1.5">
                        {active.overdue && <Badge variant="warning">Overdue</Badge>}
                        <StatusPill status={active.status} />
                      </span>
                    </DetailRow>
                    <DetailRow label="Earnings"><MoneyBadge affiliateStatus={active.affiliate_status} merchant={active.merchant} /></DetailRow>
                    {active.channel !== undefined && (
                      <DetailRow label="Channel"><span className="font-mono text-xs">{active.channel || "—"}</span></DetailRow>
                    )}
                    {active.attempts !== undefined && <DetailRow label="Attempts">{active.attempts}</DetailRow>}
                    {active.note && (
                      <DetailRow label="Last error"><span className="text-xs text-destructive">{active.note}</span></DetailRow>
                    )}
                  </div>
                </div>
                {active.source === "draft" && (
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" size="sm" onClick={() => { handleEdit(active.raw as DraftItem); setActive(null); }}>
                      <Edit className="h-4 w-4 mr-1.5" /> Edit
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => { handleDelete(active.id); setActive(null); }}>
                      <Trash2 className="h-4 w-4 mr-1.5" /> Delete
                    </Button>
                  </div>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function PostList({ rows, onOpen, onEdit, onDelete }: {
  rows: Row[]; onOpen: (r: Row) => void;
  onEdit?: (r: Row) => void; onDelete?: (id: number) => void;
}) {
  return (
    <Card className="overflow-hidden py-0">
      <CardContent className="p-0">
        <ul className="divide-y divide-border">
          {rows.map((r) => (
            <li key={r.id}>
              <div className="flex w-full items-center gap-4 px-4 py-3 transition-colors hover:bg-muted/50">
                <button onClick={() => onOpen(r)} className="min-w-0 flex-1 space-y-1 text-left">
                  <span className="inline-flex items-center gap-1.5 text-xs">
                    <Badge variant="secondary" className="font-medium">{postTypeLabel(r.post_type)}</Badge>
                    {r.merchant && <span className="text-muted-foreground">{merchantLabel(r.merchant)}</span>}
                  </span>
                  <p className="truncate text-sm text-foreground/90">
                    {firstLine(r.text) || <span className="text-muted-foreground">#{r.id}</span>}
                  </p>
                </button>
                {r.when && (
                  <button onClick={() => onOpen(r)} className="hidden shrink-0 text-right sm:block">
                    <div className="flex items-center justify-end gap-1 text-sm font-medium">
                      <HugeiconsIcon icon={Clock01Icon} className="h-3.5 w-3.5 text-muted-foreground" />
                      {relative(r.when)}
                    </div>
                    <div className="text-xs text-muted-foreground">{istDateTime(r.when)}</div>
                  </button>
                )}
                <div className="flex shrink-0 items-center gap-1.5">
                  <ReasoningTrigger rationale={r.rationale} />
                  {r.overdue && <Badge variant="warning">Overdue</Badge>}
                  <StatusPill status={r.status} />
                  {r.source === "draft" && onEdit && onDelete && (
                    <>
                      <Button variant="ghost" size="sm" onClick={() => onEdit(r)}><Edit className="h-4 w-4" /></Button>
                      <Button variant="ghost" size="sm" onClick={() => onDelete(r.id)}><Trash2 className="h-4 w-4" /></Button>
                    </>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export default function PostsPage() {
  return (
    <Suspense fallback={<div className="h-40" />}>
      <PostsInner />
    </Suspense>
  );
}
