import type { RelatedItem } from "./reference-links";
import { conceptItem } from "./reference-links";
import type { MemoryLink } from "../components/reference-links-context";

const CONCEPT_NODES = [
  { id: "preview-concept-voice-cloning", nodeKey: "concept--voice-cloning", nodeKind: "concept", displayName: "Voice cloning" },
  { id: "preview-concept-speech-synthesis", nodeKey: "concept--speech-synthesis", nodeKind: "concept", displayName: "Speech synthesis" },
  { id: "preview-concept-anthropic", nodeKey: "maker--anthropic", nodeKind: "maker", displayName: "Anthropic" },
  { id: "preview-concept-translation", nodeKey: "concept--translation", nodeKind: "concept", displayName: "Translation" },
  { id: "preview-task-translation", nodeKey: "task--translation", nodeKind: "task", displayName: "Translation (task)" },
];

const REFERENCE_ROWS = [
  { id: "preview-reference-lineage-1", title: "Council minutes on the harbour dredging contract", sourceUri: "https://records.example.org/council/harbour-dredging", sourcePublishedAt: "2026-10-27T09:00:00Z", createdAt: "2026-10-28T08:15:00Z" },
  { id: "preview-reference-lineage-2", title: "Zoning variance hearing, draft transcript", sourceUri: "https://www.example.com/hearings/zoning-variance", sourcePublishedAt: null, createdAt: "2026-10-29T14:40:00Z" },
  { id: "preview-reference-lineage-3", title: "Port authority audit, second quarter", sourceUri: "https://audits.example.net/port/q2", sourcePublishedAt: "2026-09-30T00:00:00Z", createdAt: "2026-10-30T11:05:00Z" },
  { id: "preview-reference-lineage-4", title: "Harbour dredging: contractor letter", sourceUri: "https://letters.example.org/dredging-letter", sourcePublishedAt: "2026-10-12T00:00:00Z", createdAt: "2026-10-30T17:30:00Z" },
];

export function localPreviewReferenceLinkItems(): RelatedItem[] {
  const keys = CONCEPT_NODES.map(node => node.nodeKey);
  return [
    ...CONCEPT_NODES.map(node => conceptItem(node, keys)),
    ...REFERENCE_ROWS.map(row => ({
      kind: "reference" as const, lineageId: row.id, title: row.title, hashtag: null, nodeKey: null, nodeKind: null,
      host: new URL(row.sourceUri).host.replace(/^www\./, ""), sourceUri: row.sourceUri, sourcePublishedAt: row.sourcePublishedAt, addedAt: row.createdAt,
    })),
  ];
}

export function localPreviewReferenceLinks(): MemoryLink[] {
  const reference = (id: string, object: string, objectKind: MemoryLink["objectKind"], state: MemoryLink["state"], provenance: string, similarity: number | null = null): MemoryLink => ({
    id, subjectKind: "reference", subjectLineageId: "preview-reference-lineage-0", objectKind, objectLineageId: object, state, provenance, similarity,
  });
  return [
    reference("preview-link-1", "preview-concept-voice-cloning", "semanticNode", "current", "human"),
    reference("preview-link-2", "preview-reference-lineage-1", "reference", "current", "human"),
    reference("preview-link-3", "preview-concept-speech-synthesis", "semanticNode", "suggested", "suggested", 0.81),
    reference("preview-link-4", "preview-reference-lineage-2", "reference", "suggested", "suggested", 0.74),
    { id: "preview-link-5", subjectKind: "reference", subjectLineageId: "preview-reference-lineage-3", objectKind: "semanticNode", objectLineageId: "preview-concept-voice-cloning", state: "current", provenance: "human" },
    { id: "preview-link-6", subjectKind: "reference", subjectLineageId: "preview-reference-lineage-2", objectKind: "semanticNode", objectLineageId: "preview-concept-voice-cloning", state: "current", provenance: "human" },
  ];
}
