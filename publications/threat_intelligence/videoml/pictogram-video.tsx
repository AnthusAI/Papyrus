"use client";

import type { CSSProperties } from "react";
import { createFrameDrivenPictogramMotion } from "../pictograms/video-motion";
import {
  isThreatIntelligencePictogramSlug,
  type ThreatIntelligencePictogramSlug,
} from "../pictograms/registry";
import { getPictogramRegistryEntry } from "../pictograms/art";
import { PICTOGRAM_PALETTE } from "../pictograms/system";

const PICTOGRAM_FRAME_STYLE: CSSProperties = {
  aspectRatio: "var(--pictogram-aspect-ratio, 1)",
  background: "var(--background)",
  border: "1px solid rgba(145, 145, 152, 0.28)",
  display: "block",
  overflow: "hidden",
  position: "relative",
  width: "100%",
};

const PICTOGRAM_SVG_STYLE: CSSProperties = {
  display: "block",
  height: "100%",
  width: "100%",
};

export type ThreatIntelligencePictogramVideoProps = {
  slug: string;
  size?: number;
  alt?: string;
  frame?: number;
  fps?: number;
};

export function ThreatIntelligencePictogramVideo({
  slug,
  size = 400,
  alt,
  frame = 0,
  fps = 30,
}: ThreatIntelligencePictogramVideoProps) {
  if (!isThreatIntelligencePictogramSlug(slug)) {
    return null;
  }

  const pictogramSlug: ThreatIntelligencePictogramSlug = slug;
  const entry = getPictogramRegistryEntry(pictogramSlug);
  const timing = createFrameDrivenPictogramMotion(frame, fps, pictogramSlug);
  const Pictogram = entry.render;
  const aspectRatio = entry.aspectRatio ?? 1;

  return (
    <div
      style={{
        width: size,
        height: size,
        flexShrink: 0,
        ["--pictogram-aspect-ratio" as string]: String(aspectRatio),
      }}
    >
      <div className="pictogram-figure__frame" style={PICTOGRAM_FRAME_STYLE}>
        <div style={{ ...PICTOGRAM_SVG_STYLE, height: "100%" }}>
          <Pictogram alt={alt ?? slug} palette={PICTOGRAM_PALETTE} timing={timing} />
        </div>
      </div>
    </div>
  );
}
