/**
 * What the Work section shows of a research assignment's packet. The packet is the `research` object in the `metadata` ModelAttachment of the Message that the
 * Assignment `produces` (see `apply_research_packet` in `assignments_workflow.py` and `build_packet` in `multi_search_research.py`). It is read, never copied
 * into a Message thread: Messages come only from people.
 *
 * A claim names its sources by number. The number is a source's `rank` in `source_snapshots`, so each claim links to the pages it cites.
 * `unverifiedClaims` (a claim with its `sources` and `reasons`) and `factCheck` are written by the fact-checking step when it has run; a packet without them
 * shows without them.
 */
export type PacketSource = { rank: number; url: string; title: string; domain: string | null };
export type PacketClaim = { claim: string; sources: PacketSource[] };
export type PacketDisagreement = { topic: string; positions: { position: string; sources: PacketSource[] }[] };
export type PacketUnverifiedClaim = { claim: string; sources: PacketSource[]; reasons: string[] };

export type ResearchPacketView = {
  summary: string;
  recommendedAngle: string | null;
  claims: PacketClaim[];
  disagreements: PacketDisagreement[];
  openQuestions: string[];
  unverifiedClaims: PacketUnverifiedClaim[];
  factCheckSummary: string | null;
  sourceCount: number;
};

const text = (value: unknown): string | null => (typeof value === "string" && value.trim() ? value.trim() : null);
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const record = (value: unknown): Record<string, unknown> => (typeof value === "object" && value && !Array.isArray(value) ? (value as Record<string, unknown>) : {});

function sourcesOf(numbers: unknown, byRank: Map<number, PacketSource>): PacketSource[] {
  return list(numbers).flatMap(entry => {
    const source = typeof entry === "number" ? byRank.get(entry) : undefined;
    return source ? [source] : [];
  });
}

/** The packet an Assignment produced, or null when what was stored is not a packet with a summary. Anything malformed is skipped, never thrown. */
export function researchPacketOf(raw: unknown): ResearchPacketView | null {
  const packet = record(raw);
  const summary = text(packet.summary) ?? text(record(packet.synthesis).summary);
  if (!summary) return null;
  const byRank = new Map<number, PacketSource>();
  for (const entry of list(packet.source_snapshots ?? packet.sourceSnapshots)) {
    const source = record(entry);
    const url = text(source.url);
    if (typeof source.rank === "number" && url) byRank.set(source.rank, { rank: source.rank, url, title: text(source.title) ?? url, domain: text(source.source_domain ?? source.sourceDomain) });
  }
  const claims = list(packet.claims).flatMap(entry => {
    const claim = text(record(entry).claim);
    return claim ? [{ claim, sources: sourcesOf(record(entry).sources, byRank) }] : [];
  });
  const disagreements = list(packet.disagreements).flatMap(entry => {
    const topic = text(record(entry).topic);
    const positions = list(record(entry).positions).flatMap(position => {
      const words = text(record(position).position);
      return words ? [{ position: words, sources: sourcesOf(record(position).sources, byRank) }] : [];
    });
    return topic && positions.length ? [{ topic, positions }] : [];
  });
  const unverifiedClaims = list(packet.unverifiedClaims).flatMap(entry => {
    const claim = text(record(entry).claim);
    return claim ? [{ claim, sources: sourcesOf(record(entry).sources, byRank), reasons: list(record(entry).reasons).flatMap(reason => text(reason) ?? []) }] : [];
  });
  const factCheck = packet.factCheck;
  return {
    summary,
    recommendedAngle: text(packet.recommended_angle ?? packet.recommendedAngle),
    claims,
    disagreements,
    openQuestions: list(packet.open_questions ?? packet.openQuestions).flatMap(question => text(question) ?? []),
    unverifiedClaims,
    factCheckSummary: text(factCheck) ?? text(record(factCheck).summary),
    sourceCount: byRank.size,
  };
}
