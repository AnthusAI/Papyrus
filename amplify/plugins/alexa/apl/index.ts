import { assertUniqueIds, type AplDocument } from "../contracts";
import { feedDocument } from "./feed";
import { referenceDocument } from "./reference";
import { storyDocument } from "./story";

/**
 * Every APL document of the skill. To add one, add a file in this folder that exports an `AplDocument` and add one line here
 * (keep the lines in alphabetical order). A test fails when a document file is not listed, an id appears twice, or a document is
 * not APL.
 */
export const APL_DOCUMENTS: readonly AplDocument[] = [
  feedDocument,
  referenceDocument,
  storyDocument,
];

assertUniqueIds("APL document", APL_DOCUMENTS.map((document) => document.id));

export function aplDocumentById(id: string): AplDocument {
  const found = APL_DOCUMENTS.find((document) => document.id === id);
  if (found === undefined) throw new Error(`Unknown APL document "${id}". Known: ${APL_DOCUMENTS.map((document) => document.id).join(", ")}`);
  return found;
}

/** The directive that shows one registered document on a screen. `datasources` is whatever that document binds to. */
export function aplRenderDirective(id: string, datasources: Record<string, unknown> = {}) {
  return { type: "Alexa.Presentation.APL.RenderDocument" as const, token: id, document: aplDocumentById(id).document, datasources };
}
