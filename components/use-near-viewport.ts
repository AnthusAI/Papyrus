"use client";

import { useEffect, useState, type RefObject } from "react";

export function useNearViewport(targetRef: RefObject<Element | null>, rootMargin: string): boolean {
  const [isNearViewport, setIsNearViewport] = useState(false);

  useEffect(() => {
    if (isNearViewport) return;
    const target = targetRef.current;
    if (!target) return;
    if (typeof IntersectionObserver === "undefined") {
      setIsNearViewport(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setIsNearViewport(true);
          observer.disconnect();
        }
      },
      { rootMargin },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [isNearViewport, rootMargin, targetRef]);

  return isNearViewport;
}
