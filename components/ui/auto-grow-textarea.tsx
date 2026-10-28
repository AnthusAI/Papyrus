"use client";

import { useLayoutEffect, useRef, type TextareaHTMLAttributes } from "react";

/**
 * A textarea as tall as its text. It never scrolls inside itself, so on a phone a swipe over it scrolls the page instead of
 * getting caught in the box. (CSS `field-sizing: content` does the same where supported; the height is set here for the rest.)
 */
export function AutoGrowTextarea({ className, style, value, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [value]);
  return <textarea {...props} className={className} ref={ref} rows={props.rows ?? 2} style={{ ...style, overflow: "hidden", resize: "none" }} value={value} />;
}
