"use client";

import { SparklesIcon, XIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { EditorialFinding, Span } from "../lib/editorial-checks";
import { FLAT_PRIMARY_BUTTON_CLASS, EditorialFindingCard, RewriteOptions, useRewriteOptions, type FindingActions } from "./editorial-finding-card";

/** What the popover is about: findings at a marked passage, or a passage the editor selected. */
export type PreviewPopoverTarget =
  | { kind: "findings"; findingIds: string[]; anchor: DOMRect }
  | { kind: "selection"; source: Span; anchor: DOMRect };

const WIDTH = 352;

/**
 * Floats next to the passage on the preview, inside `container` (which must be
 * positioned). Escape or the close button dismisses it.
 */
export function EditorialPreviewPopover({
  target,
  findings,
  body,
  container,
  actions,
  onClose,
}: {
  target: PreviewPopoverTarget;
  findings: EditorialFinding[];
  body: string;
  container: HTMLElement | null;
  actions: FindingActions;
  onClose: () => void;
}) {
  const [note, setNote] = useState("");
  const panel = useRef<HTMLDivElement | null>(null);
  const selectionRewrites = useRewriteOptions(actions);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    panel.current?.focus();
  }, [target]);

  const box = container?.getBoundingClientRect();
  const top = box ? target.anchor.bottom - box.top + container!.scrollTop + 6 : 0;
  const left = box ? Math.max(0, Math.min(target.anchor.left - box.left, box.width - WIDTH)) : 0;
  const shown = target.kind === "findings" ? findings.filter((finding) => target.findingIds.includes(finding.id)) : [];

  return (
    <div
      aria-label={target.kind === "findings" ? "Editorial findings for this passage" : "Rewrite the selected passage"}
      className="absolute z-20 max-h-[28rem] space-y-2 overflow-auto rounded-xl bg-popover p-3 text-sm text-popover-foreground shadow-lg outline-none"
      data-editorial-finding="popover"
      data-editorial-preview-popover={target.kind}
      ref={panel}
      role="dialog"
      style={{ top, left, width: WIDTH }}
      tabIndex={-1}
    >
      <div className="flex items-center gap-2">
        <Input
          aria-label="Note for rewrites"
          className="h-8 flex-1 border-0 bg-muted"
          onChange={(event) => setNote(event.target.value)}
          placeholder="Note for rewrites, e.g. shorter"
          value={note}
        />
        <Button className="border-0" aria-label="Close" onClick={onClose} size="icon-xs" type="button" variant="ghost">
          <XIcon aria-hidden="true" />
        </Button>
      </div>
      {target.kind === "findings" ? (
        shown.length ? (
          shown.map((finding) => <EditorialFindingCard actions={actions} active finding={finding} key={finding.id} note={note} />)
        ) : (
          <p className="text-muted-foreground">This finding was resolved.</p>
        )
      ) : (
        <div className="space-y-2" data-editorial-selection-rewrite>
          <q className="block text-muted-foreground">{body.slice(target.source.start, target.source.end)}</q>
          <Button className={FLAT_PRIMARY_BUTTON_CLASS}
            data-editorial-rewrite-selection
            onClick={() => {
              void selectionRewrites.request({ selection: target.source }, note.trim() || null);
            }}
            size="xs"
            type="button"
            variant="ghost"
          >
            <SparklesIcon aria-hidden="true" /> Suggest rewrites
          </Button>
          <RewriteOptions finding={null} onApply={actions.onApply} suggestion={selectionRewrites.suggestion} />
        </div>
      )}
    </div>
  );
}
