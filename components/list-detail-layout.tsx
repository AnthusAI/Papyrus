"use client";

import { ArrowLeftIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * The newsroom's list-and-detail layout, one rule for every page that has it (References, Messages). Below `lg` (1024px) the open
 * item's detail replaces the list at the full width with a Back button; from `lg` the detail is a pane beside the list, 24rem wide and
 * 28rem from `xl`. It is chosen by the viewport, never by the selection.
 */
export const DETAIL_PANE_WIDTH = "lg:w-[min(100%,24rem)] xl:w-[min(100%,28rem)]";
export const LIST_HIDDEN_WHEN_DETAIL_OPEN = "max-lg:hidden";

export function ListDetailLayout({ backLabel, detail, list, onBack, open }: {
  backLabel: string;
  detail: ReactNode;
  list: ReactNode;
  onBack: () => void;
  open: boolean;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 lg:flex-row lg:items-start" data-list-detail-layout={open ? "detail" : "list"}>
      <div className={cn("min-w-0 flex-1", open && LIST_HIDDEN_WHEN_DETAIL_OPEN)} data-list-detail-list>{list}</div>
      {open ? (
        <div
          className={cn("flex w-full shrink-0 flex-col gap-3 rounded-[20px] bg-[var(--feed-card)] p-4 lg:sticky lg:top-4 lg:max-h-[calc(100dvh-2rem)] lg:overflow-y-auto", DETAIL_PANE_WIDTH)}
          data-list-detail-pane
        >
          <button
            className="-ml-2 inline-flex min-h-9 items-center gap-1.5 self-start rounded-[var(--feed-radius-md,16px)] px-2 text-sm font-medium text-muted-foreground outline-none transition-colors hover:bg-[var(--feed-control)]/70 hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring lg:hidden"
            data-detail-back
            onClick={onBack}
            type="button"
          >
            <ArrowLeftIcon aria-hidden="true" className="size-4" />
            {backLabel}
          </button>
          {detail}
        </div>
      ) : null}
    </div>
  );
}
