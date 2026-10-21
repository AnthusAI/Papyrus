"use client";

import { PrimingPanel, type PrimingPanelProps } from "cyclotron/components/priming-panel";

/**
 * The "Import a file" option of the Add a reference area. Papyrus supplies the
 * transport and configuration; Cyclotron owns the preview and label controls.
 * It is only rendered by `ReferenceAddEntry`, never as a section of its own.
 */
export function ReferencePriming(props: PrimingPanelProps) {
  return (
    <PrimingPanel
      {...props}
      renderItem={props.renderItem ?? ((item) => (
        <div className="space-y-2">
          <p className="whitespace-pre-wrap text-sm">{String(item.values.abstract ?? item.values.text ?? "")}</p>
          <p className="break-all text-xs text-muted-foreground">{String(item.values.source_uri ?? "")}</p>
        </div>
      ))}
    />
  );
}
