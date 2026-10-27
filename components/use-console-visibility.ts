"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export function useConsoleVisibility({ available, persist = true }: { available: boolean; persist?: boolean }) {
  const [open, setOpen] = useState(false);
  const visible = useRef(false);
  const entry = useRef<string | null>(null);
  const setVisible = useCallback((next: boolean) => {
    visible.current = next;
    setOpen(next);
    if (persist) try { localStorage.setItem("papyrus:console-open", String(next)); } catch { /* Optional preference. */ }
  }, [persist]);
  const openConsole = useCallback(() => {
    if (!available || visible.current) return;
    const existing = history.state?.papyrusMobileChat;
    if (typeof existing === "string") entry.current = existing;
    else if (matchMedia("(max-width: 900px)").matches) {
      entry.current = crypto.randomUUID();
      history.pushState({ ...history.state, papyrusMobileChat: entry.current }, "", location.href);
    }
    setVisible(true);
  }, [available, setVisible]);
  const closeConsole = useCallback(() => {
    if (entry.current && history.state?.papyrusMobileChat === entry.current) history.back();
    else setVisible(false);
  }, [setVisible]);
  const toggleOpen = useCallback(() => {
    if (visible.current) closeConsole();
    else openConsole();
  }, [closeConsole, openConsole]);
  useEffect(() => {
    if (!available) {
      visible.current = false;
      setOpen(false);
      return;
    }
    const pop = (event: PopStateEvent) => {
      if (entry.current) setVisible(event.state?.papyrusMobileChat === entry.current);
    };
    window.addEventListener("popstate", pop);
    if (typeof history.state?.papyrusMobileChat === "string") openConsole();
    else if (persist) try { if (localStorage.getItem("papyrus:console-open") === "true") openConsole(); } catch { /* Optional preference. */ }
    return () => window.removeEventListener("popstate", pop);
  }, [available, openConsole, persist, setVisible]);
  return { open, openConsole, closeConsole, toggleOpen };
}
