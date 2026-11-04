"use client";

import { CheckIcon, CopyIcon, Share2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  DEFAULT_SHARE_EXPIRY_DAYS,
  SHARE_EXPIRY_DAYS,
  StoryShareFailure,
  describeShown,
  describeState,
  describeViewers,
  expiryLabel,
  shareUrl,
  storyShareClient,
  type ShareExpiryDays,
  type ShareViewers,
  type StoryShareClient,
  type StoryShareSummary,
} from "../lib/story-share-client";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";

type Props = {
  lineageId: string;
  /** The version open in the editor: the one "this version only" pins. */
  versionNumber: number | null;
  /** Only for tests: the origin the link is shown under. */
  origin?: string;
  client?: StoryShareClient;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
};

function Choice({ children, detail, onClick, pressed, name }: { children: React.ReactNode; detail?: string; onClick: () => void; pressed: boolean; name: string }) {
  return (
    <Button aria-pressed={pressed} className={cn("h-auto flex-col items-start gap-0.5 whitespace-normal px-3 py-2 text-left", !pressed && "text-foreground")} data-story-share-choice={name} data-pressed={pressed} onClick={onClick} type="button" variant={pressed ? "default" : "secondary"}>
      <span className="font-medium">{children}</span>
      {detail ? <span className="text-xs font-normal opacity-80">{detail}</span> : null}
    </Button>
  );
}

function Group({ label, children, name }: { label: string; children: React.ReactNode; name: string }) {
  return (
    <div className="grid gap-1.5" data-story-share-group={name} role="group" aria-label={label}>
      <p className="m-0 text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</p>
      <div className="grid gap-2 sm:grid-cols-2">{children}</div>
    </div>
  );
}

function day(moment: string | null): string {
  return moment ? moment.slice(0, 10) : "never";
}

export function StoryShareButton({ lineageId, versionNumber }: { lineageId: string; versionNumber: number | null }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button aria-label="Share a draft" data-newsroom-article-share onClick={() => setOpen(true)} size="icon-sm" title="Share a draft" type="button" variant="ghost">
        <Share2Icon aria-hidden="true" />
      </Button>
      {open ? <StoryShareDialog lineageId={lineageId} onOpenChange={setOpen} open={open} versionNumber={versionNumber} /> : null}
    </>
  );
}

export function StoryShareDialog({ lineageId, versionNumber, origin, client, open = true, onOpenChange }: Props) {
  const api = client ?? storyShareClient();
  const [viewers, setViewers] = useState<ShareViewers>("anyone");
  const [pinned, setPinned] = useState(false);
  const [days, setDays] = useState<ShareExpiryDays>(DEFAULT_SHARE_EXPIRY_DAYS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ url: string; share: StoryShareSummary } | null>(null);
  const [copied, setCopied] = useState(false);
  const [shares, setShares] = useState<StoryShareSummary[] | null>(null);

  const refresh = useCallback(async () => {
    try {
      setShares(await api.list(lineageId));
    } catch (failure) {
      setShares([]);
      setError(failure instanceof StoryShareFailure ? failure.message : "The links could not be loaded.");
    }
  }, [api, lineageId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const made = await api.create({ lineageId, viewers, version: pinned ? versionNumber : null, expiresInDays: days });
      const base = origin ?? (typeof window === "undefined" ? "" : window.location.origin);
      setCreated({ url: shareUrl(base, made.path), share: made.share });
      setCopied(false);
      await refresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The link could not be made.");
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.url);
      setCopied(true);
    } catch {
      setError("Copying did not work here. Select the link and copy it.");
    }
  };

  const revoke = async (shareId: string) => {
    setError(null);
    try {
      await api.revoke(lineageId, shareId);
      await refresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The link could not be revoked.");
    }
  };

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl" data-story-share-dialog>
        <DialogHeader>
          <DialogTitle>Share a draft</DialogTitle>
          <DialogDescription>Make a link that shows this Story in the website&apos;s public layout, marked DRAFT. It is not published and search engines are told to ignore it.</DialogDescription>
        </DialogHeader>

        {created ? (
          <div className="grid gap-3" data-story-share-created>
            <p className="m-0 text-sm font-medium">Your link is ready. This is the only time it is shown.</p>
            <input aria-label="Share link" className="h-9 w-full rounded-lg bg-muted px-3 text-sm text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50" data-story-share-url onFocus={(event) => event.currentTarget.select()} readOnly value={created.url} />
            <div className="flex flex-wrap items-center gap-2">
              <Button data-story-share-copy onClick={() => void copy()} type="button">
                {copied ? <CheckIcon aria-hidden="true" /> : <CopyIcon aria-hidden="true" />}
                {copied ? "Copied" : "Copy link"}
              </Button>
              <span className="text-xs text-muted-foreground">
                {describeViewers(created.share.viewers)} can open it until {day(created.share.expiresAt)}. {describeShown(created.share.version)}.
              </span>
            </div>
          </div>
        ) : (
          <div className="grid gap-4" data-story-share-form>
            <Group label="Who can open it" name="viewers">
              <Choice detail="Anyone who has the link can read this draft. They do not need to sign in, so only send it to people you are happy to show the draft to." name="anyone" onClick={() => setViewers("anyone")} pressed={viewers === "anyone"}>
                Anyone with the link
              </Choice>
              <Choice detail="Only editors and admins who are signed in to the newsroom. Anyone else is asked to sign in, then turned away." name="signed-in" onClick={() => setViewers("signed-in")} pressed={viewers === "signed-in"}>
                Only people signed in to the newsroom
              </Choice>
            </Group>
            <Group label="What it shows" name="shows">
              <Choice detail="Keeps showing the newest version as you save new ones." name="current" onClick={() => setPinned(false)} pressed={!pinned}>
                The current version
              </Choice>
              <Choice detail="Stays on this version, whatever you save next." name="pinned" onClick={() => setPinned(true)} pressed={pinned}>
                {versionNumber ? `Version ${versionNumber} only` : "This version only"}
              </Choice>
            </Group>
            <div className="grid gap-1.5" data-story-share-group="expires" role="group" aria-label="The link lasts">
              <p className="m-0 text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">The link lasts</p>
              <div className="flex flex-wrap gap-2">
                {SHARE_EXPIRY_DAYS.map((choice) => (
                  <Button aria-pressed={days === choice} data-pressed={days === choice} data-story-share-choice={`expires-${choice}`} key={choice} onClick={() => setDays(choice)} type="button" variant={days === choice ? "default" : "secondary"}>
                    {expiryLabel(choice)}
                  </Button>
                ))}
              </div>
            </div>
            <p className="m-0 text-xs text-muted-foreground">Publishing or spiking the Story ends its links. You can end a link yourself below.</p>
          </div>
        )}

        {error ? <p className="m-0 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive" data-story-share-error role="alert">{error}</p> : null}

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end" data-story-share-actions>
          {created ? (
            <>
              <Button data-story-share-another onClick={() => setCreated(null)} type="button" variant="secondary">Make another link</Button>
              <Button data-story-share-done onClick={() => onOpenChange?.(false)} type="button">Done</Button>
            </>
          ) : (
            <>
              <Button onClick={() => onOpenChange?.(false)} type="button" variant="secondary">Cancel</Button>
              <Button data-story-share-create disabled={busy} onClick={() => void create()} type="button">Create link</Button>
            </>
          )}
        </div>

        <section className="grid gap-2" data-story-share-list>
          <p className="m-0 text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">Links to this Story</p>
          {shares === null ? <p className="m-0 text-sm text-muted-foreground">Loading…</p> : shares.length === 0 ? <p className="m-0 text-sm text-muted-foreground" data-story-share-none>No links yet.</p> : (
            <ul className="m-0 grid list-none gap-2 p-0">
              {shares.map((share) => (
                <li className="grid gap-1 rounded-lg bg-muted px-3 py-2 text-sm" data-story-share-row={share.shareId} data-state={share.state} key={share.shareId}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{describeState(share)}</span>
                    {share.state === "active" ? <Button data-story-share-revoke={share.shareId} onClick={() => void revoke(share.shareId)} size="sm" type="button" variant="destructive">Revoke</Button> : null}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    Made by {share.createdBy ?? "unknown"} on {day(share.createdAt)}. {describeViewers(share.viewers)}. {describeShown(share.version)}.
                  </span>
                  <span className="text-xs text-muted-foreground">Expires {day(share.expiresAt)}. Last opened {day(share.lastOpenedOn)}{share.openCount ? `, opened ${share.openCount} ${share.openCount === 1 ? "time" : "times"}` : ""}.</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </DialogContent>
    </Dialog>
  );
}
