"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

export function PapyrusConsoleFrame({ available, open, reserveSpace, onOpen, onClose, page, children }: {
  available: boolean;
  open: boolean;
  reserveSpace: boolean;
  onOpen: () => void;
  onClose: () => void;
  page: ReactNode;
  children: ReactNode;
}) {
  const [mobile, setMobile] = useState(false);
  const [viewport, setViewport] = useState<{ top: number; height: number } | null>(null);
  const panel = useRef<HTMLElement>(null);
  const modal = available && open && mobile;

  useEffect(() => {
    const media = window.matchMedia("(max-width: 900px)");
    const update = () => setMobile(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (!modal) return;
    const visual = window.visualViewport;
    const update = () => setViewport({ top: visual?.offsetTop ?? 0, height: visual?.height ?? window.innerHeight });
    update();
    visual?.addEventListener("resize", update);
    visual?.addEventListener("scroll", update, { passive: true });
    return () => {
      visual?.removeEventListener("resize", update);
      visual?.removeEventListener("scroll", update);
    };
  }, [modal]);

  useEffect(() => {
    if (!modal) return;
    const previous = document.activeElement;
    const frame = requestAnimationFrame(() => panel.current?.querySelector<HTMLElement>("button")?.focus());
    return () => {
      cancelAnimationFrame(frame);
      requestAnimationFrame(() => {
        if (previous instanceof HTMLElement && previous !== document.body && previous.isConnected && !previous.closest("[inert]")) previous.focus();
        else Array.from(document.querySelectorAll<HTMLElement>(".papyrus-console-mobile-trigger, .edition-progress__button--console, .papyrus-console__header button")).find(element => element.getClientRects().length > 0)?.focus();
      });
    };
  }, [modal]);

  return <>
    <div className={reserveSpace ? "papyrus-console-page papyrus-console-page--open" : "papyrus-console-page"} inert={modal || undefined}>{page}</div>
    {available && !open ? <button className="papyrus-console-mobile-trigger" type="button" aria-label="Open private chat" aria-expanded={false} aria-controls="papyrus-console-panel" onClick={onOpen}>Chat</button> : null}
    {available ? <aside ref={panel} id="papyrus-console-panel" className={open ? "papyrus-console papyrus-console--open" : "papyrus-console"} aria-label="Papyrus console" role={modal ? "dialog" : undefined} aria-modal={modal || undefined}
      style={modal && viewport ? { top: viewport.top, height: viewport.height, bottom: "auto" } : undefined}
      onKeyDown={event => {
        if (!modal) return;
        if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
        if (event.key !== "Tab") return;
        const focusable = Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]') ?? []).filter(element => element.getClientRects().length > 0);
        const first = focusable[0], last = focusable.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }}>{children}</aside> : null}
  </>;
}
