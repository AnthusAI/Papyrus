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
export type PacketClaim = { claim: string; sources: PacketSource[]; snippetOnly?: boolean };
export type PacketDisagreement = { topic: string; positions: { position: string; sources: PacketSource[] }[] };
/** `rejected` is what packets made before the check told "contradicted" from "not shown" say; it reads as `not_shown`. */
export type ClaimVerdict = "needs_check" | "contradicted" | "not_shown" | "rejected" | "unchecked";
export type HeldGroup = "contradicted" | "not_shown" | "needs_check" | "unchecked";
export type PacketUnverifiedClaim = { claim: string; sources: PacketSource[]; verdict: ClaimVerdict | null; reasons: string[] };

/** A machine reason from the fact check (`fact_check.py`), in plain words. A reason it does not know is shown as it is. */
export function plainReason(reason: string): string {
  const unmatched = /^unmatched_terms:\s*(.+)$/.exec(reason);
  if (unmatched) return `Not in the cited source: ${unmatched[1]}`;
  if (/^judge_failed\b/.test(reason)) return /short of time/.test(reason) ? "The run ran short of time before this claim was checked" : "The second check could not run";
  const known: Record<string, string> = {
    judge_partly_supported: "The source only partly supports this",
    judge_contradicted: "A source says otherwise",
    judge_not_supported: "The sources this run had do not show this",
    judge_source_silent: "The source does not say this",
    quote_not_in_source: "The quotation is not in the source",
    attribution_lost: "The claim drops who said it",
    no_cited_text: "No text of the cited source was read",
    no_judge: "The second check was not run",
  };
  return known[reason] ?? reason;
}

/** The group a held claim belongs to. A packet from before the split, or a claim with no verdict at all, says `rejected` or nothing: that reads as not shown only when it says `rejected`. */
export function heldGroup(verdict: ClaimVerdict | null): HeldGroup {
  return verdict === "contradicted" ? "contradicted" : verdict === "not_shown" || verdict === "rejected" ? "not_shown" : verdict === "unchecked" ? "unchecked" : "needs_check";
}

/** Each group's heading and, where the label alone could be misread, one plain sentence. Not shown is not false: only "contradicted" says a source states otherwise. */
export const HELD_GROUP_TEXT: Record<HeldGroup, { heading: string; note: string | null }> = {
  contradicted: { heading: "Contradicted by its sources", note: null },
  not_shown: { heading: "Not shown by the sources this run had", note: "This does not mean they are false. The sources this run had did not show them." },
  needs_check: { heading: "Needs a check", note: null },
  unchecked: { heading: "Not checked", note: null },
};
export const HELD_GROUP_ORDER: HeldGroup[] = ["contradicted", "not_shown", "needs_check", "unchecked"];

export function verdictLabel(verdict: ClaimVerdict | null): string {
  const group = heldGroup(verdict);
  return group === "contradicted" ? "Contradicted" : group === "not_shown" ? "Not shown" : group === "unchecked" ? "Not checked" : "Needs a check";
}

const count = (counts: Record<string, unknown>, key: string): number => (typeof counts[key] === "number" && Number.isFinite(counts[key]) ? counts[key] as number : 0);

/** "12 verified, 8 need a check, 2 contradicted, 6 not shown by the sources; 23 rest on one site", from the counts of `factCheck`. Parts that are zero are left out, except verified. */
export function factCheckSentence(counts: Record<string, unknown>): string {
  const parts = [`${count(counts, "verified")} verified`];
  if (count(counts, "needs_check")) parts.push(`${count(counts, "needs_check")} need a check`);
  if (count(counts, "contradicted")) parts.push(`${count(counts, "contradicted")} contradicted`);
  const notShown = count(counts, "not_shown") + count(counts, "rejected");      // a packet from before the split counts them all as rejected
  if (notShown) parts.push(`${notShown} not shown by the sources`);
  if (count(counts, "unchecked")) parts.push(`${count(counts, "unchecked")} not checked`);
  const single = count(counts, "singleSource");
  return parts.join(", ") + (single ? `; ${single} rest on one site` : "");
}

/** "Read 12 of 15 sources, 3 of them in part. 2 could not be opened and 1 had no room left, so claims from them rest on search snippets." */
export function readingSentence(reading: Record<string, unknown>): string {
  const part = count(reading, "inPart");
  const unopened = list(reading.notOpened).length;
  const noRoom = list(reading.outOfRoom).length;
  const missed = [unopened ? `${unopened} could not be opened` : "", noRoom ? `${noRoom} opened with no time or room left to read` : ""].filter(Boolean).join(" and ");
  return `Read ${count(reading, "read")} of ${count(reading, "sources")} sources${part ? `, ${part} of them in part` : ""}.` +
    (missed ? ` ${missed}, so claims from them rest on search snippets.` : "");
}

export type PacketDirectionGap = { name: string; note: string };

export type ResearchPacketView = {
  summary: string;
  recommendedAngle: string | null;
  claims: PacketClaim[];
  disagreements: PacketDisagreement[];
  openQuestions: string[];
  unverifiedClaims: PacketUnverifiedClaim[];
  factCheckSummary: string | null;
  /** What the run read, in words; null for a packet from before runs opened their sources, which rests on search snippets alone. */
  readingSummary: string | null;
  notOpened: string[];
  directionGaps: PacketDirectionGap[];
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
    return claim ? [{ claim, sources: sourcesOf(record(entry).sources, byRank), snippetOnly: record(entry).snippetOnly === true }] : [];
  });
  const reading = record(record(packet.multiSearch).reading);
  const notOpened = list(reading.notOpened).flatMap(url => text(url) ?? []);
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
    const raw = record(entry).verdict;
    const verdict: ClaimVerdict | null = raw === "rejected" || raw === "contradicted" || raw === "not_shown" || raw === "unchecked" || raw === "needs_check" ? raw : null;
    return claim ? [{ claim, sources: sourcesOf(record(entry).sources, byRank), verdict, reasons: list(record(entry).reasons).flatMap(reason => text(reason) ?? []).map(plainReason) }] : [];
  });
  const factCheck = record(packet.factCheck);
  const counts = record(factCheck.counts);
  const directionGaps = list(factCheck.directionGaps).flatMap(entry => {
    const name = text(record(entry).name);
    return name ? [{ name, note: text(record(entry).note) ?? `The run wrote nothing on ${name}.` }] : [];
  });
  return {
    summary,
    recommendedAngle: text(packet.recommended_angle ?? packet.recommendedAngle),
    claims,
    disagreements,
    openQuestions: list(packet.open_questions ?? packet.openQuestions).flatMap(question => text(question) ?? []),
    unverifiedClaims,
    factCheckSummary: Object.keys(counts).length ? factCheckSentence(counts) : text(packet.factCheck) ?? text(factCheck.summary),
    readingSummary: typeof reading.sources === "number" ? readingSentence(reading) : null,
    notOpened,
    directionGaps,
    sourceCount: byRank.size,
  };
}
