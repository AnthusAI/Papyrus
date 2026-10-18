"use client";

import { useEffect } from "react";

type Excerpt = { issueId: string; text: string };

const EXCERPT_TOGGLE_THRESHOLD = 130;

function buildExcerptElement(text: string): HTMLElement {
  const container = document.createElement("div");
  container.className = "board-card-excerpt";
  container.dataset.boardCardExcerpt = "";
  container.dataset.expanded = "false";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  container.append(paragraph);
  if (text.length > EXCERPT_TOGGLE_THRESHOLD) {
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.textContent = "More";
    toggle.setAttribute("aria-expanded", "false");
    const flip = (event: Event) => {
      event.stopPropagation();
      const expanded = container.dataset.expanded !== "true";
      container.dataset.expanded = String(expanded);
      toggle.textContent = expanded ? "Less" : "More";
      toggle.setAttribute("aria-expanded", String(expanded));
    };
    toggle.addEventListener("click", flip);
    toggle.addEventListener("keydown", event => event.stopPropagation());
    container.append(toggle);
  }
  return container;
}

/**
 * Adds a short expandable excerpt under each card's headline. The Kanbus card has no excerpt slot,
 * so each excerpt is written into the card's content block once the card is on the page.
 */
export function BoardCardExcerpts({ excerpts, scope }: { excerpts: readonly Excerpt[]; scope: HTMLElement | null }) {
  useEffect(() => {
    if (!scope) return;
    const textByIssueId = new Map(excerpts.map(({ issueId, text }) => [issueId, text]));
    const place = () => {
      for (const card of Array.from(scope.querySelectorAll<HTMLElement>(".issue-card"))) {
        const text = textByIssueId.get(card.dataset.issueId ?? "");
        const content = card.querySelector<HTMLElement>(".issue-card-content");
        if (!text || !content) continue;
        const existing = content.querySelector<HTMLElement>(":scope > [data-board-card-excerpt]");
        if (existing && existing.querySelector("p")?.textContent === text) continue;
        existing?.remove();
        content.querySelector("h3")?.after(buildExcerptElement(text));
      }
    };
    place();
    const observer = new MutationObserver(place);
    observer.observe(scope, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [excerpts, scope]);
  return null;
}
