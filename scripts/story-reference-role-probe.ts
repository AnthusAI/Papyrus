// Runs the site's own setStoryReferenceRole code (amplify/functions/category-action/story-reference-role.ts) on one row in memory and prints
// what it wrote. Used by features_backend/story-reference-role.feature, whose stand-in site hands every setStoryReferenceRole call here.
import { readFileSync } from "node:fs";
import { setStoryReferenceRole, type StoryReferenceRow } from "../amplify/functions/category-action/story-reference-role";

type Probe = { relations: Record<string, StoryReferenceRow>; call: { relationId: string; role: string; citationKey?: string | null; note?: string | null }; callerGroups: string[]; actor: string; now: string; origin?: string };

async function main() {
  const input = JSON.parse(readFileSync(0, "utf8")) as Probe;
  const relations = new Map(Object.entries(input.relations));
  const writes: Record<string, unknown>[] = [];
  try {
    const result = await setStoryReferenceRole(
      {
        getRelation: async (id) => relations.get(id) ?? null,
        updateRelation: async (patch) => {
          writes.push(patch);
          relations.set(patch.id, { ...(relations.get(patch.id) as StoryReferenceRow), ...patch });
        },
      },
      { ...input.call, callerGroups: input.callerGroups, actor: input.actor, now: input.now, origin: input.origin ?? null },
    );
    console.log(JSON.stringify({ result, writes }));
  } catch (error) {
    console.log(JSON.stringify({ error: (error as Error).message, writes }));
  }
}
void main();
