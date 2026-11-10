"use client";

import { ImageIcon, ImageOffIcon, LoaderIcon } from "lucide-react";
import { useState } from "react";
import type { HeadlineImageState } from "../lib/story-headline-image";

/**
 * The Story's headline (card and sharing) picture, read-only, at the top of the Story detail so a reviewer sees it with the text. Flat colours and
 * rounded corners, no outlines. Every state says something: no picture, still loading or processing, missing or unreadable.
 */
export function StoryHeadlineImage({ state }: { state: HeadlineImageState }) {
  const [broken, setBroken] = useState<string | null>(null);
  const shell = "flex items-start gap-2 rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-control)]/60 p-3 text-sm";
  if (state.status === "ready" && broken !== state.url) {
    return (
      <figure className="space-y-1.5" data-story-headline-image="ready">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img alt={state.alt} className="aspect-[16/9] w-full rounded-[var(--feed-radius-md,16px)] bg-muted object-cover" onError={() => setBroken(state.url)} src={state.url} />
        <figcaption className="text-xs text-muted-foreground">Headline image ({state.ref.key}). {state.alt ? `Alt text: ${state.alt}` : "No alt text is set."}</figcaption>
      </figure>
    );
  }
  if (state.status === "ready") {
    return (
      <p className={shell} data-story-headline-image="broken" role="status">
        <ImageOffIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <span><strong>The headline image did not load.</strong> {state.ref.key} points to {state.ref.value}, but the browser could not open the picture.</span>
      </p>
    );
  }
  if (state.status === "none") {
    return (
      <p className={shell} data-story-headline-image="none" role="status">
        <ImageIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <span><strong>No headline image.</strong> This version sets none of image, cover, ogImage or thumbnail, so cards and shares have no picture.</span>
      </p>
    );
  }
  if (state.status === "loading" || state.status === "processing") {
    return (
      <p className={shell} data-story-headline-image={state.status} role="status">
        <LoaderIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <span>{state.status === "loading" ? "Loading the headline image." : <><strong>The headline image is still processing.</strong> Its file has not finished uploading; check again shortly.</>}</span>
      </p>
    );
  }
  return (
    <p className={shell} data-story-headline-image="missing" role="status">
      <ImageOffIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span><strong>The headline image cannot be shown.</strong> {state.reason}</span>
    </p>
  );
}
