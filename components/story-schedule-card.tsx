"use client";

import { useEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import type { NativeBoardIssue } from "../lib/newsroom-board";
import { publicationTimeZone } from "../lib/site-publication";
import { StoryScheduleBadge } from "./story-schedule-badge";

const STORY_CARD_SELECTOR = '.issue-card[data-issue-id^="contentItem:"]';
const SLOT_ATTRIBUTE = "data-story-card-schedule";

/**
 * The Kanbus card has no slot for the schedule, so each Story card gets one empty container on its own line under the owner row and the badge is drawn into
 * it through a portal, the way the checklist progress is (story-checklist-card.tsx). The container takes no clicks, so a tap lands on the card, and it is
 * found again whenever the board changes. Nothing here touches what Kanbus renders.
 */
export function useStoryScheduleSlots(root: RefObject<HTMLElement | null>, enabled: boolean): Map<string, HTMLElement> {
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
        let slot = row.parentElement?.querySelector<HTMLElement>(`:scope > [${SLOT_ATTRIBUTE}]`) ?? null;
        if (!slot) {
          slot = document.createElement("div");
          slot.setAttribute(SLOT_ATTRIBUTE, "");
          slot.className = "story-card-schedule-slot";
          row.insertAdjacentElement("afterend", slot);
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

/** One line on each scheduled Story card: an icon and the time in the publication's zone, or Overdue, or Superseded. */
export function StoryCardSchedule({ issues, slots }: { issues: readonly NativeBoardIssue[]; slots: Map<string, HTMLElement> }) {
  const zone = publicationTimeZone();
  if (!zone) return null;
  const now = new Date();
  return <>{issues.map(issue => {
    const slot = issue.kind === "contentItem" && issue.schedule ? slots.get(issue.id) : undefined;
    if (!slot || !issue.schedule) return null;
    return createPortal(<span data-story-schedule={issue.nativeId}><StoryScheduleBadge schedule={issue.schedule} zone={zone} now={now} /></span>, slot, issue.id);
  })}</>;
}
