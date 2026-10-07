"use client";

import { useEffect, useState, type RefObject } from "react";
import type { BlogHeaderObstacle } from "./blog-page-background";

const HEADER_OBSTACLE_SELECTORS = [
  ".presentation-header__eyebrow",
  ".presentation-header__word",
  ".presentation-header__meta",
  ".presentation-header__subtitle",
  ".presentation-header__date",
  ".presentation-header__tagline",
  ".presentation-section-nav a",
];

function measureObstacleRect(element: HTMLElement): DOMRect {
  const range = document.createRange();
  range.selectNodeContents(element);
  const contentRect = range.getBoundingClientRect();
  range.detach();
  if (contentRect.width > 0 && contentRect.height > 0) return contentRect;
  return element.getBoundingClientRect();
}

/**
 * Measures the rendered header text (eyebrow, masthead words, meta, tagline,
 * section links) as rectangles in the coordinates of `.blog-page-background`,
 * so a brand's background artwork can keep clear of them. Block-level header
 * elements span the full page width even when their text ends mid-line, so
 * the text range is measured instead of the element box.
 */
export function useBlogHeaderObstacles(
  pageRef: RefObject<HTMLElement | null>,
  paintBuffer: number,
): BlogHeaderObstacle[] {
  const [obstacles, setObstacles] = useState<BlogHeaderObstacle[]>([]);

  useEffect(() => {
    const page = pageRef.current;
    if (!page) return;

    const update = () => {
      const background = page.querySelector<HTMLElement>(".blog-page-background");
      const backgroundRect = background?.getBoundingClientRect();
      if (!backgroundRect) return;

      const next: BlogHeaderObstacle[] = [];
      for (const selector of HEADER_OBSTACLE_SELECTORS) {
        for (const element of Array.from(page.querySelectorAll<HTMLElement>(selector))) {
          const rect = measureObstacleRect(element);
          const intersectionTop = Math.max(rect.top, backgroundRect.top);
          const intersectionBottom = Math.min(rect.bottom, backgroundRect.bottom);
          const intersectionLeft = Math.max(rect.left, backgroundRect.left);
          const intersectionRight = Math.min(rect.right, backgroundRect.right);
          const width = intersectionRight - intersectionLeft;
          const height = intersectionBottom - intersectionTop;
          if (width <= 0 || height <= 0) continue;
          next.push({
            x: intersectionLeft - backgroundRect.left,
            y: intersectionTop - backgroundRect.top,
            width,
            height: height + paintBuffer * 2,
          });
        }
      }
      setObstacles(next);
    };

    update();
    const observer = new ResizeObserver(update);
    observer.observe(page);
    window.addEventListener("resize", update);
    void document.fonts?.ready.then(update);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [pageRef, paintBuffer]);

  return obstacles;
}
