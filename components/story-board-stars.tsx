"use client";

import { useEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import type { NativeBoardIssue } from "../lib/newsroom-board";
import { StarsMark } from "./star-rating";
import type { StoryStarsController } from "./use-story-stars";

const STORY_CARD_SELECTOR = '.issue-card[data-issue-id^="contentItem:"]';
const SLOT_ATTRIBUTE = "data-story-card-stars";

/**
 * The Kanbus card has no slot for a mark, so each Story card gets one empty container in its top row, before the Generated or Started by a person label,
 * and the rating is drawn into it through a portal. A React click in a portal never reaches the card's own handler, so the container takes no clicks
 * and a tap lands on the card. The containers are found again whenever the board changes (a card that moves column is a new element), and a container
 * whose card is gone is dropped. Nothing here touches what Kanbus renders.
 */
export function useStoryCardSlots(root: RefObject<HTMLElement | null>, enabled: boolean): Map<string, HTMLElement> {
  const [slots, setSlots] = useState<Map<string, HTMLElement>>(new Map());
  useEffect(() => {
    const board = root.current;
    if (!enabled || !board) { setSlots(previous => (previous.size ? new Map() : previous)); return; }
    const scan = () => {
      const found = new Map<string, HTMLElement>();
      for (const card of board.querySelectorAll<HTMLElement>(STORY_CARD_SELECTOR)) {
        const id = card.getAttribute("data-issue-id");
        const row = card.querySelector<HTMLElement>(".issue-accent-row");
        if (!id || !row) continue;
        let slot = row.querySelector<HTMLElement>(`:scope > [${SLOT_ATTRIBUTE}]`);
        if (!slot) {
          slot = document.createElement("span");
          slot.setAttribute(SLOT_ATTRIBUTE, "");
          slot.className = "pointer-events-none ml-auto inline-flex h-3.5 shrink-0 items-center empty:hidden";
          row.insertBefore(slot, row.lastElementChild);
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

/**
 * The rating of every rated Story card on the board: a solid star and the number, nothing on an unrated card. Editors rate a Story in its drawer or its
 * editor, not here, so a card spends no row on it and a tap on the mark opens the Story like the rest of the card.
 */
export function StoryCardStars({ issues, slots, controller }: { issues: readonly NativeBoardIssue[]; slots: Map<string, HTMLElement>; controller: Pick<StoryStarsController, "value"> }) {
  return <>{issues.map(issue => {
    const slot = issue.kind === "contentItem" && issue.starRating !== undefined ? slots.get(issue.id) : undefined;
    if (!slot) return null;
    const stars = controller.value(issue.nativeId, issue.starRating ?? null);
    return createPortal(<span data-story-stars={issue.nativeId}><StarsMark stars={stars} /></span>, slot, issue.id);
  })}</>;
}
