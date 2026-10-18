type EditorialRecord = Record<string, any>;
type Result = { data?: EditorialRecord | EditorialRecord[] | null; errors?: unknown; nextToken?: string | null };
type EditorialClient = { models: { Item: { itemBySlug: (args: { slug: string }, options: { limit: number; nextToken?: string | null }) => Promise<Result> }; NewsroomSection: { get: (args: { id: string }) => Promise<Result> } } };

function checked(response: Result, operation: string) {
  if (Array.isArray(response.errors) && response.errors.length) throw new Error(`${operation}: ${JSON.stringify(response.errors)}`);
  return response;
}

export async function resolveAssignmentDoctrine(client: EditorialClient, assignment: EditorialRecord) {
  const context: EditorialRecord[] = [];
  for (const kind of ["mission", "policy"]) {
    const slug = `editorial-doctrine-${kind}`;
    const rows: EditorialRecord[] = [];
    let nextToken: string | null | undefined;
    do {
      const response = checked(await client.models.Item.itemBySlug({ slug }, { limit: 100, nextToken }), "read publication doctrine");
      rows.push(...(response.data as EditorialRecord[] ?? []));
      nextToken = response.nextToken;
    } while (nextToken);
    const current = rows.filter(row => row.type === "doctrine" && row.status === "private" && row.versionState === "current");
    if (current.length !== 1) throw new Error(`Publication ${kind}: expected one current record, found ${current.length}`);
    const body = current[0].bodyMarkus ? [current[0].bodyMarkus] : (current[0].body ?? []).filter((value: string) => value.trim());
    if (!body.length) throw new Error(`Required publication ${kind} is empty`);
    context.push({ scope: "publication", kind, label: `Editorial ${kind}`, slug, body });
  }
  const sectionId = assignment.sectionKey || assignment.sectionId;
  if (sectionId) {
    const response = checked(await client.models.NewsroomSection.get({ id: sectionId }), "read editorial section");
    const section = response.data as EditorialRecord | null;
    if (!section) throw new Error(`Requested section not found: ${sectionId}`);
    for (const [kind, key] of [["mission", "editorialMission"], ["policy", "editorialPolicy"], ["guidance", "assignmentGuidance"], ["kill criteria", "killCriteria"]] as const) {
      context.push({ scope: "desk", kind, label: `Section ${kind}`, slug: `desk-section-${sectionId}-${kind.replaceAll(" ", "-")}`, body: section[key] ? [section[key]] : [], categoryKey: sectionId, categoryLineageId: sectionId });
    }
  }
  return context;
}
