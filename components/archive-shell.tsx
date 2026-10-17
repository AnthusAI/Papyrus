"use client";

import type { ReactNode } from "react";
import { useRhythmOverlay } from "./use-rhythm-overlay";

type ArchiveShellProps = {
  children: ReactNode;
};

export function ArchiveShell({ children }: ArchiveShellProps) {
  const showRhythmOverlay = useRhythmOverlay();

  return (
    <main
      className="archive-page archive-rhythm-shell"
      data-rhythm-overlay={showRhythmOverlay ? "true" : "false"}
    >
      {children}
    </main>
  );
}
