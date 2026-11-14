"use client";

import { useEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { ListChecks } from "lucide-react";
import type { NativeBoardIssue } from "../lib/newsroom-board";
import { checklistProgressLabel, checklistProgressText } from "../lib/story-checklist";

const STORY_CARD_SELECTOR = '.issue-card[data-issue-id^="contentItem:"]';
const SLOT_ATTRIBUTE = "data-story-card-checklist";

/**
 * The Kanbus card has no slot for progress, so each Story card gets one empty container in its owner row (the line under the headline) and the progress is
 * drawn into it through a portal, the way the rating is (story-board-stars.tsx). The container takes no clicks, so a tap lands on the card, and it is found
 * again whenever the board changes. Nothing here touches what Kanbus renders.
 */
export function useStoryChecklistSlots(root: RefObject<HTMLElement | null>, enabled: boolean): Map<string, HTMLElement> {
  const [slots, setSlots] = useState<Map<string, HTMLElement>>(new Map());
  useEffect(() => {
    const board = root.current;
    if (!enabled || !board) { setSlots(previous => (previous.size ? new Map() : previous)); return; }
    const scan = () => {
      const found = new Map<string, HTMLElement>();
      for (const card of board.querySelectorAll<HTMLElement>(STORY_CARD_SELECTOR)) {
        const id = card.getAttribute("data-issue-id");
        const row = card.querySelector<HTMLElement>(".issue-card-owner");
        if (!id || !row) continue;
        let slot = row.querySelector<HTMLElement>(`:scope > [${SLOT_ATTRIBUTE}]`);
        if (!slot) {
          slot = document.createElement("span");
          slot.setAttribute(SLOT_ATTRIBUTE, "");
          slot.className = "story-card-checklist-slot";
          row.insertBefore(slot, row.firstChild);
        }
        found.set(id, slot);
      }
      setSlots(previous => {
        const same = previous.size === found.size && [...found].every(([id, slot]) => previous.get(id) === slot);
        return same ? previous : found;
      });
    };
    scan();
    const observer = new MutationObserver(scan);
    observer.observe(board, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [root, enabled]);
  return slots;
}

/** One line on each Story card that has a checklist, for example `4/9 · 2 skipped`, with an icon and the words for a screen reader. */
export function StoryCardChecklist({ issues, slots }: { issues: readonly NativeBoardIssue[]; slots: Map<string, HTMLElement> }) {
  return <>{issues.map(issue => {
    const slot = issue.kind === "contentItem" && issue.checklist ? slots.get(issue.id) : undefined;
    if (!slot || !issue.checklist) return null;
    return createPortal(
      <span className="story-card-checklist" data-story-checklist-progress={issue.nativeId} title={checklistProgressLabel(issue.checklist)} aria-label={checklistProgressLabel(issue.checklist)}>
        <ListChecks aria-hidden size={13} /><span aria-hidden>{checklistProgressText(issue.checklist)}</span>
      </span>,
      slot, issue.id,
    );
  })}</>;
}
