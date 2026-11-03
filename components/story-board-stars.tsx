"use client";

import { useEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import type { NativeBoardIssue } from "../lib/newsroom-board";
import { StarRating } from "./star-rating";
import type { StoryStarsController } from "./use-story-stars";

const STORY_CARD_SELECTOR = '.issue-card[data-issue-id^="contentItem:"]';
const SLOT_ATTRIBUTE = "data-story-card-stars";
const STORY_STARS_LABEL = "Rating · optional";

/** The id the save uses: the version the card was read from. Any version of the Story names it. */
export function storyVersionId(issue: Pick<NativeBoardIssue, "href">): string {
  return decodeURIComponent(issue.href.split("/").pop() ?? "");
}

/**
 * The Kanbus card has no slot for a control, so each Story card gets one empty container inside its content, and the star rating is drawn into it
 * through a portal. The containers are found again whenever the board changes (a card that moves column is a new element), and a container whose
 * card is gone is dropped. Nothing here touches what Kanbus renders.
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
        const content = card.querySelector<HTMLElement>(".issue-card-content");
        if (!id || !content) continue;
        let slot = content.querySelector<HTMLElement>(`:scope > [${SLOT_ATTRIBUTE}]`);
        if (!slot) {
          slot = document.createElement("div");
          slot.setAttribute(SLOT_ATTRIBUTE, "");
          slot.className = "pt-1";
          content.appendChild(slot);
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

/** The rating control of every Story card on the board. A card whose rating was not read from the Item (a published-only row) has none. */
export function StoryCardStars({ issues, slots, controller }: { issues: readonly NativeBoardIssue[]; slots: Map<string, HTMLElement>; controller: StoryStarsController }) {
  return <>{issues.map(issue => {
    const slot = issue.kind === "contentItem" && issue.starRating !== undefined ? slots.get(issue.id) : undefined;
    if (!slot) return null;
    const saved = issue.starRating ?? null;
    return createPortal(
      <div data-story-stars={issue.nativeId}>
        <StarRating
          feedback={controller.feedback(issue.nativeId)}
          label={STORY_STARS_LABEL}
          onChange={stars => controller.tap(issue.nativeId, storyVersionId(issue), saved, stars)}
          value={controller.value(issue.nativeId, saved)}
        />
      </div>,
      slot,
      issue.id,
    );
  })}</>;
}
