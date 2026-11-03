"use client";

import { FilePlus2Icon, Loader2Icon } from "lucide-react";
import Link from "next/link";
import * as navigation from "next/navigation";
import { useState } from "react";
import { STORY_ITEM_TYPES } from "../lib/content-item-lifecycle";
import type { ExistingStory } from "../lib/content-actions-client";
import { getNewsroomNavHref } from "../lib/newsroom-nav";
import { resolveArticlesBackend } from "../lib/newsroom-articles";
import { createStoryCaption } from "../lib/story-from-reference";
import { cn } from "@/lib/utils";

/**
 * The app router, or null where there is none (a surface that is not mounted in the Next app, such as the fixtures of the feed tests, stubs
 * `next/navigation` without a router or has no app router at all): the Story then opens with a plain navigation.
 */
function useOptionalRouter(): { push: (href: string) => void } | null {
  try {
    return navigation.useRouter?.() ?? null;
  } catch {
    return null;
  }
}

const LABEL = "font-[family-name:var(--font-sans)] text-[10px] font-extrabold tracking-[0.07em] uppercase";

/** What the local preview needs to build the draft, because it has no backend to read the Reference from. The real action ignores it. */
export type CreateStoryPreview = { title: string; url: string | null; summary: string | null; imageUrl: string | null; site: string | null };

/**
 * One tap makes a Story from a Reference and opens it in the article editor, ready to write (`createStoryFromReference`, PPY-3c11bd).
 *
 * The Story is an article by default; where the site has the post type, a small "as a post" button beside it makes a post instead, with no dialog.
 * Making a Story from a Reference the editor has not decided also accepts it (the editor's own Accept, recorded through the same path as the Accept button, with
 * no reason asked); a rejected Reference is not overturned, and the button says so. A Reference that already has a Story is not given a second one silently:
 * the button offers the existing Story, and "Create another" is a deliberate second tap.
 */
export function CreateStoryButton({
  automatic = false,
  demo = false,
  disabled = false,
  onAccept,
  preview,
  referenceId,
  size = "compact",
  stable = false,
  status,
}: {
  /** The Reference stands accepted automatically: Create Story confirms it as the editor's own vote (Ryan: creating a Story means accepting). */
  automatic?: boolean;
  demo?: boolean;
  disabled?: boolean;
  /** Records the editor's Accept of a pending Reference (the same call as the Accept button). Not called for a Reference already accepted or rejected. */
  onAccept?: () => Promise<void> | void;
  preview?: CreateStoryPreview;
  referenceId: string;
  size?: "compact" | "large";
  /** Reserve the note's line even when there is none, so a card in a grid keeps its height when its Reference is decided. */
  stable?: boolean;
  status: string;
}) {
  const router = useOptionalRouter();
  const [busy, setBusy] = useState(false);
  const [existing, setExisting] = useState<ExistingStory[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const caption = createStoryCaption(status, automatic);
  const offersPost = STORY_ITEM_TYPES.includes("post");
  const cell = size === "large" ? "min-h-12 text-base" : "min-h-10 text-sm";

  async function create(itemType: string, again = false) {
    if (busy || disabled) return;
    setBusy(true);
    setError(null);
    try {
      const result = await resolveArticlesBackend(demo).actions.createStoryFromReference({ referenceId, itemType, again, ...(preview ? { preview } : {}) });
      if (!result.created) {
        setExisting(result.existing);
        return;
      }
      setExisting(null);
      if ((status === "pending" || automatic) && onAccept) {
        try {
          await onAccept();
        } catch (failure) {
          // The Story exists; say that the Accept did not go through, and let the editor open the Story anyway.
          setError(`The Story was made, but the Reference could not be accepted: ${failure instanceof Error ? failure.message : "try Accept again."}`);
          setExisting([{ itemId: result.itemId, lineageId: result.lineageId, title: result.title, stage: result.stage }]);
          return;
        }
      }
      const href = getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(result.itemId)}`, demo);
      if (router) router.push(href);
      else window.location.assign(href);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The Story could not be made.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-y-1.5" data-create-story data-create-story-status={status}>
      <div className="flex gap-x-1.5">
        <button
          aria-busy={busy || undefined}
          className={cn(
            "inline-flex min-w-0 flex-1 items-center justify-center gap-1.5 rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-control)] px-3 font-medium text-foreground outline-none transition-colors hover:bg-[var(--feed-control)]/70 focus-visible:ring-[3px] focus-visible:ring-ring",
            cell,
            (disabled || busy) && "opacity-[var(--feed-quiet,0.6)]",
          )}
          data-create-story-button
          disabled={disabled}
          onClick={() => void create("article")}
          type="button"
        >
          {busy ? <Loader2Icon aria-hidden="true" className="size-4 animate-spin" /> : <FilePlus2Icon aria-hidden="true" className="size-4" />}
          {caption.label}
        </button>
        {offersPost ? (
          <button
            className={cn("inline-flex items-center justify-center rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-control)]/45 px-3 text-muted-foreground outline-none transition-colors hover:bg-[var(--feed-control)]/70 hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring", cell, (disabled || busy) && "opacity-[var(--feed-quiet,0.6)]")}
            data-create-story-post
            disabled={disabled}
            onClick={() => void create("post")}
            type="button"
          >
            As a post
          </button>
        ) : null}
      </div>
      {stable ? (
        <p aria-hidden={caption.note ? undefined : true} className={cn(LABEL, "h-4 truncate leading-4 text-muted-foreground")} {...(caption.note ? { "data-create-story-note": "" } : {})}>{caption.note}</p>
      ) : caption.note ? <p className={cn(LABEL, "text-muted-foreground")} data-create-story-note>{caption.note}</p> : null}
      {existing ? (
        <div className="grid gap-y-1 rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-control)]/45 p-3 text-sm" data-create-story-existing role="status">
          <p>{existing.length === 1 ? "A Story already exists for this Reference:" : `${existing.length} Stories already exist for this Reference:`}</p>
          <ul className="grid gap-y-0.5">
            {existing.map((story) => (
              <li key={story.itemId}>
                <Link className="font-medium underline underline-offset-4" data-create-story-open href={getNewsroomNavHref(`/newsroom/articles/${encodeURIComponent(story.itemId)}`, demo)}>{story.title || "Open the Story"}</Link>
                {story.stage ? <span className="text-muted-foreground"> · {story.stage}</span> : null}
              </li>
            ))}
          </ul>
          <button
            className="justify-self-start rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-control)] px-3 py-1.5 font-medium text-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring"
            data-create-story-another
            onClick={() => void create("article", true)}
            type="button"
          >
            Create another
          </button>
        </div>
      ) : null}
      {error ? <p className="text-xs text-destructive" role="alert">{error}</p> : null}
    </div>
  );
}
