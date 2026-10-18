"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

type Excerpt = { issueId: string; text: string };

function CardExcerpt({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  return <div className="board-card-excerpt" data-board-card-excerpt data-expanded={expanded}>
    <p>{text}</p>
    {text.length > 130 && <button aria-expanded={expanded} onClick={event => { event.stopPropagation(); setExpanded(open => !open); }} onKeyDown={event => event.stopPropagation()} type="button">{expanded ? "Less" : "More"}</button>}
  </div>;
}

/**
 * Adds a short expandable excerpt under each card's headline. The Kanbus card has no excerpt slot,
 * so each excerpt is rendered into the card's content block once the card is on the page.
 */
export function BoardCardExcerpts({ excerpts, scope }: { excerpts: readonly Excerpt[]; scope: HTMLElement | null }) {
  const [hosts, setHosts] = useState<{ host: HTMLElement; text: string }[]>([]);
  useEffect(() => {
    if (!scope) return;
    const collect = () => {
      const found = excerpts.flatMap(({ issueId, text }) => {
        const card = Array.from(scope.querySelectorAll<HTMLElement>(".issue-card")).find(candidate => candidate.dataset.issueId === issueId);
        const content = card?.querySelector<HTMLElement>(".issue-card-content");
        if (!content) return [];
        let host = content.querySelector<HTMLElement>(":scope > [data-board-card-excerpt-host]");
        if (!host) {
          host = document.createElement("div");
          host.dataset.boardCardExcerptHost = "true";
          content.querySelector("h3")?.after(host);
        }
        return [{ host, text }];
      });
      setHosts(previous => previous.length === found.length && previous.every((entry, index) => entry.host === found[index].host && entry.text === found[index].text) ? previous : found);
    };
    collect();
    const observer = new MutationObserver(collect);
    observer.observe(scope, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [excerpts, scope]);
  return <>{hosts.map(({ host, text }, index) => createPortal(<CardExcerpt text={text} />, host, `${index}`))}</>;
}
