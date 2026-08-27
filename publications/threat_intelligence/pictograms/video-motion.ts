import {
  getThreatIntelligencePictogramPhaseOffset,
  PICTOGRAM_CYCLE_MS,
  type ThreatIntelligencePictogramSlug,
} from "./registry";
import type { PictogramMotion } from "./system";

export function createFrameDrivenPictogramMotion(
  frame: number,
  fps: number,
  slug: ThreatIntelligencePictogramSlug,
): PictogramMotion {
  const phaseOffsetMs = getThreatIntelligencePictogramPhaseOffset(slug);
  const cycleS = PICTOGRAM_CYCLE_MS / 1000;
  const epochMs = ((frame / fps) * 1000) % PICTOGRAM_CYCLE_MS;
  const phase = ((epochMs + phaseOffsetMs) % PICTOGRAM_CYCLE_MS) / PICTOGRAM_CYCLE_MS;

  return {
    cycleS,
    phase,
    prefersReducedMotion: false,
    delayS: (offsetMs = 0) => -(((epochMs + phaseOffsetMs + offsetMs) % PICTOGRAM_CYCLE_MS) / 1000),
  };
}
