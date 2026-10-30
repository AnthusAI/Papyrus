/**
 * The state of the References feed for one visit: the pages loaded so far for each (sort, show) choice, the attachments and decisions read
 * for them, the cards rated this visit, and a cheap count of what arrived since the visit began. No React and no network of its own: a
 * `ReferenceFeedSource` does the reading, and `components/use-reference-feed-pages.ts` hands this to a component.
 *
 * Nothing already on screen moves. A page is appended; rating patches the card in place; a refresh of a record keeps its place; items that
 * arrive after the visit began wait behind a pill until the editor asks (`showNew`).
 */
import type { ReferenceAttachmentRecord, ReferenceRecord } from "./category-repository";
import {
  FEED_PAGE_SIZE,
  ReferenceFeedPager,
  isRated,
  lineageOf,
  referenceProbability,
  type FeedCompanions,
  type ReferenceFeedSource,
} from "./reference-feed-pages";
import { UNDECIDED_PROBABILITY, type FeedShow, type FeedSort } from "./reference-feed-ranking";
import { normalizeReferenceCurationStatus } from "./reference-policy";
import type { RelevanceDecisionView } from "./relevance-decisions";

export type FeedStatus = "idle" | "loading" | "ready" | "error";

export type FeedState = {
  sort: FeedSort;
  show: FeedShow;
  /** The loaded References of the active choice, in display order, with this visit's ratings applied. */
  records: ReferenceRecord[];
  /** References fetched on their own (a deep link) that are not in the loaded pages. */
  extra: ReferenceRecord[];
  attachments: ReferenceAttachmentRecord[];
  decisions: Map<string, RelevanceDecisionView>;
  /** The first page: idle until asked for, loading, ready, or failed. */
  status: FeedStatus;
  loadingMore: boolean;
  hasMore: boolean;
  error: string | null;
  /** True while attachments and decisions of newly loaded cards are being read. */
  companionsPending: boolean;
  companionsError: string | null;
  /** The lead card, fixed when the first page arrived: never a predicted Reject. */
  leadId: string | undefined;
  /** Unrated References that arrived since the visit began and are not shown. */
  newCount: number;
  /** Whether anything has been rated yet; known only once the unrated stream has been found empty. */
  hasRated: boolean;
  /** Lineage ids rated during this visit. */
  visitRated: ReadonlySet<string>;
};

export type FeedStats = { pageRequests: number; companionRequests: number; referenceRequests: number; newChecks: number };

export class ReferenceFeedController {
  private readonly pagers = new Map<string, ReferenceFeedPager>();
  private readonly leads = new Map<string, string | undefined>();
  private readonly errors = new Map<string, string>();
  private readonly overrides = new Map<string, ReferenceRecord>();
  private readonly patches = new Map<string, Partial<ReferenceRecord>>();
  private readonly extra = new Map<string, ReferenceRecord>();
  private readonly attachments = new Map<string, ReferenceAttachmentRecord[]>();
  private readonly decisions = new Map<string, RelevanceDecisionView>();
  private readonly companioned = new Set<string>();
  private readonly inFlight = new Set<string>();
  private readonly visitRated = new Set<string>();
  private readonly listeners = new Set<() => void>();
  private active: { sort: FeedSort; show: FeedShow } = { sort: "best", show: "unrated" };
  private companionsPending = 0;
  private companionsError: string | null = null;
  private newCount = 0;
  private hasRated = false;
  private version = 0;
  private cached: { version: number; state: FeedState } | null = null;
  private disposed = false;
  private visitStartedAt: string;
  readonly stats: FeedStats = { pageRequests: 0, companionRequests: 0, referenceRequests: 0, newChecks: 0 };

  constructor(
    private readonly source: ReferenceFeedSource,
    private readonly options: { pageSize?: number; now?: () => number } = {},
  ) {
    this.visitStartedAt = new Date(this.now()).toISOString();
  }

  private now(): number {
    return this.options.now ? this.options.now() : Date.now();
  }

  // --- Observation ---------------------------------------------------------------------------------------------------------------

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private emit() {
    this.version += 1;
    if (this.disposed) return;
    for (const listener of [...this.listeners]) listener();
  }

  getState = (): FeedState => {
    if (this.cached?.version === this.version) return this.cached.state;
    const key = this.key();
    const pager = this.pagers.get(key);
    const error = this.errors.get(key) ?? null;
    const records = (pager?.records ?? []).map((record) => this.current(record));
    const state: FeedState = {
      ...this.active,
      records,
      extra: [...this.extra.values()].map((record) => this.current(record)),
      attachments: [...this.attachments.values()].flat(),
      decisions: new Map(this.decisions),
      status: error && !pager?.firstPageLoaded ? "error" : pager?.firstPageLoaded ? "ready" : pager ? "loading" : "idle",
      loadingMore: Boolean(pager?.busy && pager.firstPageLoaded),
      hasMore: Boolean(pager) && !pager!.exhausted,
      error,
      companionsPending: this.companionsPending > 0,
      companionsError: this.companionsError,
      leadId: this.leads.get(key),
      newCount: this.newCount,
      hasRated: this.hasRated,
      visitRated: new Set(this.visitRated),
    };
    this.cached = { version: this.version, state };
    return state;
  };

  private key(sort = this.active.sort, show = this.active.show): string {
    return `${sort}:${show}`;
  }

  private current(record: ReferenceRecord): ReferenceRecord {
    const lineage = lineageOf(record);
    const base = this.overrides.get(lineage) ?? record;
    const patch = this.patches.get(lineage);
    return patch ? { ...base, ...patch } : base;
  }

  /** A loaded or fetched Reference by lineage id, with this visit's changes applied. */
  find(lineageId: string): ReferenceRecord | null {
    for (const pager of this.pagers.values()) {
      const found = pager.records.find((record) => lineageOf(record) === lineageId);
      if (found) return this.current(found);
    }
    const extra = this.extra.get(lineageId);
    return extra ? this.current(extra) : null;
  }

  private loadedLineages(): Set<string> {
    const known = new Set<string>(this.extra.keys());
    for (const pager of this.pagers.values()) for (const record of pager.records) known.add(lineageOf(record));
    return known;
  }

  // --- Paging --------------------------------------------------------------------------------------------------------------------

  /** Choose the sort and show. The first time a choice is made its first page loads; a choice already loaded keeps its pages and places. */
  activate(sort: FeedSort, show: FeedShow) {
    this.active = { sort, show };
    const key = this.key();
    let pager = this.pagers.get(key);
    if (!pager) {
      pager = new ReferenceFeedPager(this.source, sort, show, this.options.pageSize ?? FEED_PAGE_SIZE);
      this.pagers.set(key, pager);
    }
    if (!pager.firstPageLoaded && !pager.busy) void this.load(key, pager);
    else this.emit();
  }

  /** Read the next page of the active choice. Does nothing while a page is loading or when there is no more. */
  loadMore(): Promise<void> {
    const key = this.key();
    const pager = this.pagers.get(key);
    if (!pager || pager.busy || pager.exhausted) return Promise.resolve();
    return this.load(key, pager);
  }

  /** Try again after a failed page. */
  retry(): Promise<void> {
    const key = this.key();
    const pager = this.pagers.get(key);
    if (!pager) return Promise.resolve();
    this.errors.delete(key);
    return this.load(key, pager);
  }

  private async load(key: string, pager: ReferenceFeedPager): Promise<void> {
    this.errors.delete(key);
    const before = pager.requests;
    const first = !pager.firstPageLoaded;
    this.emit();
    try {
      await pager.loadMore();
    } catch (failure) {
      this.errors.set(key, failure instanceof Error ? failure.message : "The References could not be loaded.");
    }
    this.stats.pageRequests += pager.requests - before;
    if (first && pager.firstPageLoaded && !this.leads.has(key)) this.leads.set(key, this.leadOf(pager));
    this.emit();
    await this.loadCompanions(pager.records);
    if (first && pager.firstPageLoaded && pager.records.length === 0 && pager.exhausted && pager.show === "unrated") await this.probeRated();
  }

  /** The lead card is the first unrated card, unless it is a predicted Reject. Fixed once, so a later page never changes it. */
  private leadOf(pager: ReferenceFeedPager): string | undefined {
    const first = pager.records.find((record) => !isRated(this.current(record)));
    if (!first) return undefined;
    return referenceProbability(first, undefined) >= UNDECIDED_PROBABILITY ? lineageOf(first) : undefined;
  }

  private async probeRated() {
    try {
      this.hasRated = await this.source.hasRated();
    } catch {
      this.hasRated = false;
    }
    this.emit();
  }

  // --- Companions: attachments and decisions, per page ---------------------------------------------------------------------------

  private async loadCompanions(records: ReferenceRecord[]) {
    const wanted = records.filter((record) => !this.companioned.has(lineageOf(record)) && !this.inFlight.has(lineageOf(record)));
    if (!wanted.length) return;
    for (const record of wanted) this.inFlight.add(lineageOf(record));
    this.companionsPending += 1;
    this.emit();
    try {
      this.stats.companionRequests += 1;
      const companions = await this.source.fetchCompanions(wanted);
      this.takeCompanions(wanted, companions);
      this.companionsError = null;
    } catch (failure) {
      this.companionsError = failure instanceof Error ? failure.message : "Predictions could not be loaded.";
    } finally {
      for (const record of wanted) this.inFlight.delete(lineageOf(record));
      this.companionsPending -= 1;
      this.emit();
    }
  }

  private takeCompanions(records: ReferenceRecord[], companions: FeedCompanions) {
    for (const record of records) {
      const lineage = lineageOf(record);
      this.companioned.add(lineage);
      this.attachments.set(lineage, companions.attachments.filter((attachment) => attachment.referenceLineageId === lineage));
    }
    for (const [lineage, decision] of companions.decisions) this.decisions.set(lineage, decision);
  }

  /** For a host that keeps the data in memory and changes it (a background refresh): read the loaded cards' companions again. */
  async refreshCompanions() {
    const loaded = [...this.loadedLineages()].flatMap((lineage) => this.find(lineage) ?? []);
    if (!loaded.length) return;
    try {
      this.takeCompanions(loaded, await this.source.fetchCompanions(loaded));
    } catch (failure) {
      this.companionsError = failure instanceof Error ? failure.message : "Predictions could not be loaded.";
    }
    this.emit();
  }

  // --- Records that change while the page is open --------------------------------------------------------------------------------

  /** A newer copy of Reference records the host holds. Loaded cards take it in place; nothing is added or moved. */
  mergeRecords(records: ReferenceRecord[]) {
    const loaded = this.loadedLineages();
    let changed = false;
    for (const record of records) {
      const lineage = lineageOf(record);
      if (!loaded.has(lineage)) continue;
      const known = this.overrides.get(lineage) ?? this.find(lineage);
      if (known && sameRecord(known, record)) continue;
      this.overrides.set(lineage, record);
      changed = true;
    }
    if (changed) this.emit();
  }

  /** Apply a change to a loaded card in place: a rating's new status, for one. The card keeps its place. */
  patch(lineageId: string, fields: Partial<ReferenceRecord>) {
    this.patches.set(lineageId, { ...this.patches.get(lineageId), ...fields });
    if (fields.curationStatus !== undefined && isRated({ curationStatus: fields.curationStatus } as ReferenceRecord)) this.visitRated.add(lineageId);
    this.emit();
  }

  markVisitRated(lineageId: string) {
    if (this.visitRated.has(lineageId)) return;
    this.visitRated.add(lineageId);
    this.emit();
  }

  /** Open a Reference that is not in the loaded pages (a deep link) without loading the feed. */
  async ensureReference(idOrLineageId: string): Promise<ReferenceRecord | null> {
    const loaded = this.find(idOrLineageId);
    if (loaded) return loaded;
    this.stats.referenceRequests += 1;
    const fetched = await this.source.fetchReference(idOrLineageId);
    if (!fetched || this.disposed) return fetched;
    this.extra.set(lineageOf(fetched), fetched);
    this.emit();
    await this.loadCompanions([fetched]);
    return fetched;
  }

  // --- New arrivals ----------------------------------------------------------------------------------------------------------------

  /** The cheap check behind the "N new items" pill: References that arrived after the visit began. Run on focus. */
  async checkNew() {
    this.stats.newChecks += 1;
    try {
      const count = await this.source.countNew({ since: this.visitStartedAt, known: this.loadedLineages() });
      if (count !== this.newCount) { this.newCount = count; this.emit(); }
    } catch {
      // The pill is a convenience; a failed check leaves it as it was.
    }
  }

  /** The editor asked for the new items: start the visit over from the first page of the active choice. */
  showNew() {
    this.visitStartedAt = new Date(this.now()).toISOString();
    this.pagers.clear();
    this.leads.clear();
    this.errors.clear();
    this.newCount = 0;
    this.hasRated = false;
    this.activate(this.active.sort, this.active.show);
  }

  dispose() {
    this.disposed = true;
    this.listeners.clear();
  }
}

function sameRecord(left: ReferenceRecord, right: ReferenceRecord): boolean {
  const keys = new Set([...Object.keys(left), ...Object.keys(right)]) as Set<keyof ReferenceRecord>;
  for (const key of keys) {
    if (key === "metadata") continue;
    if (left[key] !== right[key]) return false;
  }
  return true;
}

/** The status a rating leaves, for patching a card in place. */
export function ratedFields(choice: "accept" | "reject" | "archive" | "reopen", note: string | null | undefined, now: string): Partial<ReferenceRecord> {
  const status = choice === "accept" ? "accepted" : choice === "reject" ? "rejected" : choice === "archive" ? "archived" : "pending";
  return { curationStatus: normalizeReferenceCurationStatus(status), curationStatusReason: note ?? null, curationStatusUpdatedAt: now };
}
