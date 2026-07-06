import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "./button";

export function Pagination({ page, pages, total, onPage }: {
  page: number; pages: number; total: number; onPage: (p: number) => void;
}) {
  if (pages <= 1) return <p className="text-xs text-muted-foreground">{total} item{total === 1 ? "" : "s"}</p>;
  return (
    <div className="flex items-center justify-between gap-3">
      <p className="text-xs text-muted-foreground">
        Page {page} of {pages} · {total} items
      </p>
      <div className="flex items-center gap-1">
        <Button variant="outline" size="icon" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft size={16} />
        </Button>
        <Button variant="outline" size="icon" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          <ChevronRight size={16} />
        </Button>
      </div>
    </div>
  );
}
