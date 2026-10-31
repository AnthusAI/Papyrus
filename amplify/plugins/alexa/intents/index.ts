import { assertUniqueIds, type IntentModule } from "../contracts";
import { aplUserEventIntent } from "./apl-user-event";
import { launchIntent } from "./launch";

/**
 * Every intent module of the skill. To add an intent, add a file in this folder that exports an `IntentModule` and add one line
 * here (keep the lines in alphabetical order). A test fails when a module file is not listed, or an id appears twice.
 * Handlers are tried in this order: put specific handlers before catch-alls.
 */
export const INTENT_MODULES: readonly IntentModule[] = [
  aplUserEventIntent,
  launchIntent,
];

assertUniqueIds("intent", INTENT_MODULES.map((module) => module.id));
