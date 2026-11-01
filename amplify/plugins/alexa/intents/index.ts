import { assertUniqueIds, type IntentModule } from "../contracts";
import { aplUserEventIntent } from "./apl-user-event";
import { cancelIntent } from "./cancel";
import { continueIntent } from "./continue";
import { fallbackIntent } from "./fallback";
import { headlinesIntent } from "./headlines";
import { helpIntent } from "./help";
import { launchIntent } from "./launch";
import { navigateHomeIntent } from "./navigate-home";
import { nextIntent } from "./next";
import { previousIntent } from "./previous";
import { readStoryIntent } from "./read-story";
import { repeatIntent } from "./repeat";
import { reviewAcceptIntent } from "./review-accept";
import { reviewBulkIntent } from "./review-bulk";
import { reviewDoneIntent } from "./review-done";
import { reviewReasonIntent } from "./review-reason";
import { reviewRejectIntent } from "./review-reject";
import { reviewRemainingIntent } from "./review-remaining";
import { reviewSendIntent } from "./review-send";
import { reviewSkipIntent } from "./review-skip";
import { reviewSourceIntent } from "./review-source";
import { reviewStartIntent } from "./review-start";
import { reviewTouchIntent } from "./review-touch";
import { reviewUndoIntent } from "./review-undo";
import { reviewWhyIntent } from "./review-why";
import { sessionEndedIntent } from "./session-ended";
import { stopIntent } from "./stop";

/**
 * Every intent module of the skill. To add an intent, add a file in this folder that exports an `IntentModule` and add one line
 * here (keep the lines in alphabetical order). A test fails when a module file is not listed, or an id appears twice.
 * Handlers are tried in this order: put specific handlers before catch-alls. (Each one here matches exactly one request type or
 * intent name, so their order does not matter.)
 */
export const INTENT_MODULES: readonly IntentModule[] = [
  aplUserEventIntent,
  cancelIntent,
  continueIntent,
  fallbackIntent,
  headlinesIntent,
  helpIntent,
  launchIntent,
  navigateHomeIntent,
  nextIntent,
  previousIntent,
  readStoryIntent,
  repeatIntent,
  reviewAcceptIntent,
  reviewBulkIntent,
  reviewDoneIntent,
  reviewReasonIntent,
  reviewRejectIntent,
  reviewRemainingIntent,
  reviewSendIntent,
  reviewSkipIntent,
  reviewSourceIntent,
  reviewStartIntent,
  reviewTouchIntent,
  reviewUndoIntent,
  reviewWhyIntent,
  sessionEndedIntent,
  stopIntent,
];

assertUniqueIds("intent", INTENT_MODULES.map((module) => module.id));
