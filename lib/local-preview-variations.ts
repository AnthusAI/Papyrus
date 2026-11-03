import type { StoryVariationView } from "./story-variations";

/**
 * Sample variations for the local preview (no AWS): one idea has three ways to connect and a Story in reporting has only one. They are not on the first idea of the
 * board, which the layout tests open and which must keep the height it has without any.
 */
const FIRST_IDEA = "preview-item-lineage-idea-1";
const SECOND_IDEA = "preview-item-lineage-reporting-0";

function seed(): Map<string, StoryVariationView[]> {
  const base = { storyLineageId: FIRST_IDEA, origin: "generated", bodyMarkus: null, section: null, decidedByLabel: null, decidedAt: null, decisionReason: null } as const;
  return new Map<string, StoryVariationView[]>([
    [FIRST_IDEA, [
      {
        ...base, id: "variation-preview-1", variationNumber: 1, status: "offered",
        point: "The redistricting maps move four schools' boundaries but leave the two largest untouched, so the crowding the board cites is not addressed.",
        headline: "The redistricting maps leave the two crowded schools alone",
        deck: "Four boundaries move; the two largest schools keep theirs.",
        bodyMarkus: "Four boundaries move in the maps the board published. [1]\n\n## Source\n\n1. School board redistricting maps",
        connections: [{ kind: "reference", id: "preview-auto-reference-lineage-2", title: "What the school board's redistricting maps leave out", how: "The item this idea is about" }],
        pointCheck: { verdict: "adds", claim: "The maps leave the two largest schools unchanged.", reason: "It states a claim the maps alone do not make." },
      },
      {
        ...base, id: "variation-preview-2", variationNumber: 2, status: "offered",
        point: "The council's zoning vote last month put three new developments inside the two crowded schools' catchments, which suggests the maps and the zoning were never read together.",
        headline: "Zoning and school maps were decided separately",
        deck: "Three developments approved in October sit inside the two crowded catchments.",
        connections: [{ kind: "reference", id: "preview-auto-reference-lineage-3", title: "Zoning reversal: the three documents behind the vote", how: "Linked by an editor" }],
        pointCheck: { verdict: "adds", claim: "The developments fall inside the crowded catchments.", reason: "It draws a comparison neither source makes." },
      },
      {
        ...base, id: "variation-preview-3", variationNumber: 3, status: "offered",
        point: "An earlier story on enrolment forecasts found the same two schools over capacity in April, so the board has had this figure for months.",
        headline: "The board had the capacity figures in April",
        deck: "A story from April counted both schools above capacity.",
        connections: [
          { kind: "story", id: "demo-article-published", title: "Published: harbor safety review", how: "Rests on the same Reference" },
          { kind: "concept", id: "preview-concept-capacity", title: "#school-capacity", how: "Tagged by an editor" },
        ],
        pointCheck: { verdict: "adds", claim: "A second instance of the gap.", reason: "It connects two instances neither states." },
      },
    ]],
    [SECOND_IDEA, [{
      ...base, storyLineageId: SECOND_IDEA, id: "variation-preview-4", variationNumber: 1, status: "offered",
      point: "The revised ferry timetable is dated the day it took effect, so commuters learned of the last crossing on the quay.",
      headline: "The last ferry crossing moved with no warning",
      deck: "The revised timetable is dated the same day it took effect.",
      connections: [{ kind: "reference", id: "preview-auto-reference-lineage-1", title: "Daily ferry timetable, revised", how: "The item this idea is about" }],
      pointCheck: { verdict: "adds", claim: "The timetable took effect the day it was dated.", reason: "A claim the page does not state." },
    }]],
  ]);
}

let store: Map<string, StoryVariationView[]> | null = null;

/** The sample idea batch of the notification center (lib/review-fixture.ts) names its ideas `idea-1` and `idea-2`: they carry the same sample variations. */
const BATCH_ALIASES: Record<string, string> = { "idea-1": FIRST_IDEA, "idea-2": SECOND_IDEA };

export function previewVariations(lineageId: string): StoryVariationView[] {
  store ??= seed();
  const alias = BATCH_ALIASES[lineageId];
  return (store.get(alias ?? lineageId) ?? []).map((row) => ({ ...row, storyLineageId: lineageId }));
}

export function updatePreviewVariation(next: StoryVariationView, demoteOthers: boolean): void {
  store ??= seed();
  const key = BATCH_ALIASES[next.storyLineageId] ?? next.storyLineageId;
  const rows = store.get(key) ?? [];
  store.set(key, rows.map((row) => (row.id === next.id ? next : demoteOthers && row.status === "accepted" ? { ...row, status: "offered" } : row)));
}

export function resetPreviewVariations(): void {
  store = null;
}
