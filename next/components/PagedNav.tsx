"use client";

import { ReactNode } from "react";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationLink,
  PaginationPrevious,
  PaginationNext,
  PaginationEllipsis,
} from "@/components/ui/pagination";

function PageButton({ page, current, onClick }: { page: number; current: number; onClick: (p: number) => void }) {
  return (
    <PaginationItem>
      <div onClick={() => onClick(page)}>
        <PaginationLink isActive={page === current}>{page}</PaginationLink>
      </div>
    </PaginationItem>
  );
}

function renderPageNumbers(current: number, total: number, onPageChange: (p: number) => void) {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => (
      <PageButton key={i + 1} page={i + 1} current={current} onClick={onPageChange} />
    ));
  }

  const pages: ReactNode[] = [<PageButton key={1} page={1} current={current} onClick={onPageChange} />];

  if (current > 3) pages.push(<PaginationItem key="es"><PaginationEllipsis /></PaginationItem>);

  const start = Math.max(2, current - 1);
  const end = Math.min(total - 1, current + 1);
  for (let i = start; i <= end; i++) pages.push(<PageButton key={i} page={i} current={current} onClick={onPageChange} />);

  if (current < total - 2) pages.push(<PaginationItem key="ee"><PaginationEllipsis /></PaginationItem>);

  pages.push(<PageButton key={total} page={total} current={current} onClick={onPageChange} />);

  return pages;
}

/** Shared windowed-numbers pagination control (first/last + current±1, ellipses
 * beyond 7 pages) — the one reusable implementation for every paginated page. */
export function PagedNav({ page, pages, onPageChange, className }: {
  page: number; pages: number; onPageChange: (p: number) => void; className?: string;
}) {
  if (pages <= 1) return null;
  return (
    <Pagination className={className}>
      <PaginationContent>
        <PaginationItem>
          <PaginationPrevious
            onClick={() => onPageChange(Math.max(1, page - 1))}
            className={page <= 1 ? "pointer-events-none opacity-50" : "cursor-pointer"}
          />
        </PaginationItem>
        {renderPageNumbers(page, pages, onPageChange)}
        <PaginationItem>
          <PaginationNext
            onClick={() => onPageChange(Math.min(pages, page + 1))}
            className={page >= pages ? "pointer-events-none opacity-50" : "cursor-pointer"}
          />
        </PaginationItem>
      </PaginationContent>
    </Pagination>
  );
}
