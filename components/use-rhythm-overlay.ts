"use client";

import { useEffect, useState } from "react";

export function useRhythmOverlay(): boolean {
  const [showRhythmOverlay, setShowRhythmOverlay] = useState(false);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (isEditableEventTarget(event.target)) return;
      if ((event.key === "=" || event.code === "Equal") && event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        setShowRhythmOverlay((current) => !current);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return showRhythmOverlay;
}

function isEditableEventTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  if (tagName === "input" || tagName === "textarea" || tagName === "select") return true;
  return target.isContentEditable || target.closest("[contenteditable='true']") !== null;
}
