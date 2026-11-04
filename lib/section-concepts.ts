export type CoreConcept = { conceptLineageId: string; note: string | null; addedBy: string | null; addedAt: string | null };

/** The section's core concepts as stored: a JSON string (or the list itself) of {conceptLineageId, note, addedBy, addedAt}. A site without the field gives none. */
export function parseCoreConcepts(raw: unknown): CoreConcept[] {
  let value: unknown = raw;
  if (typeof raw === "string" && raw.trim()) {
    try { value = JSON.parse(raw); } catch { return []; }
  }
  if (!Array.isArray(value)) return [];
  const found = new Map<string, CoreConcept>();
  for (const entry of value) {
    if (!entry || typeof entry !== "object") continue;
    const row = entry as Record<string, unknown>;
    const id = typeof row.conceptLineageId === "string" ? row.conceptLineageId.trim() : "";
    if (id && !found.has(id)) {
      found.set(id, {
        conceptLineageId: id,
        note: typeof row.note === "string" && row.note.trim() ? row.note : null,
        addedBy: typeof row.addedBy === "string" ? row.addedBy : null,
        addedAt: typeof row.addedAt === "string" ? row.addedAt : null,
      });
    }
  }
  return [...found.values()];
}

export function serializeCoreConcepts(list: readonly CoreConcept[]): string {
  return JSON.stringify(list);
}

export function addCoreConcept(list: readonly CoreConcept[], conceptLineageId: string, addedBy: string, now: string): CoreConcept[] {
  return list.some(entry => entry.conceptLineageId === conceptLineageId) ? [...list] : [...list, { conceptLineageId, note: null, addedBy, addedAt: now }];
}

export function removeCoreConcept(list: readonly CoreConcept[], conceptLineageId: string): CoreConcept[] {
  return list.filter(entry => entry.conceptLineageId !== conceptLineageId);
}

export function setCoreConceptNote(list: readonly CoreConcept[], conceptLineageId: string, note: string): CoreConcept[] {
  return list.map(entry => (entry.conceptLineageId === conceptLineageId ? { ...entry, note: note.trim() ? note : null } : entry));
}

/** What to call a core concept when its node has not been read: the name part of its lineage id. */
export function fallbackConceptName(conceptLineageId: string): string {
  const afterKind = conceptLineageId.split("--").slice(1).join("--");
  return (afterKind || conceptLineageId).replace(/-/g, " ");
}

export function sectionsWithCoreConcept<T extends { coreConcepts?: unknown }>(sections: readonly T[], conceptLineageId: string): T[] {
  return sections.filter(section => parseCoreConcepts(section.coreConcepts).some(entry => entry.conceptLineageId === conceptLineageId));
}
