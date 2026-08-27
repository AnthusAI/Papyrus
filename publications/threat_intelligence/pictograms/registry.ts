export const PICTOGRAM_CYCLE_MS = 20_000;
export const PICTOGRAM_NODE_RADIUS = 4.75;
export const PICTOGRAM_EDGE_WIDTH = 2.5;

export const THREAT_INTELLIGENCE_PICTOGRAM_PHASE_OFFSETS = {
  hero: 1_400,
  "the-balance-of-power-is-shifting": 0,
  "how-our-newsroom-learns": 2_600,
  "audit-aws-exposure-before-attackers-do": 5_000,
  "audit-azure-blast-radius-before-attackers-do": 7_500,
  "treat-openai-accounts-like-production-infrastructure": 10_000,
  "how-to-play-games-securely": 12_500,
} as const;

export type ThreatIntelligencePictogramSlug = Exclude<
  keyof typeof THREAT_INTELLIGENCE_PICTOGRAM_PHASE_OFFSETS,
  "hero"
>;

export const THREAT_INTELLIGENCE_PICTOGRAM_SLUGS = Object.keys(THREAT_INTELLIGENCE_PICTOGRAM_PHASE_OFFSETS).filter(
  (key): key is ThreatIntelligencePictogramSlug => key !== "hero",
);

export function isThreatIntelligencePictogramSlug(slug: string): slug is ThreatIntelligencePictogramSlug {
  return THREAT_INTELLIGENCE_PICTOGRAM_SLUGS.includes(slug as ThreatIntelligencePictogramSlug);
}

export function getThreatIntelligencePictogramPhaseOffset(slug: ThreatIntelligencePictogramSlug): number {
  return THREAT_INTELLIGENCE_PICTOGRAM_PHASE_OFFSETS[slug];
}
