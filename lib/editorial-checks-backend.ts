import type { EditorialCheckResult, EditorialFeedbackInput, EditorialFinding, RewriteResult, Span } from "./editorial-checks";
import type { EditorialSettings } from "./editorial-checks-settings";

/** What the article editor needs from editorial checks: the site's GraphQL API, or the demo. */
export type EditorialChecksBackend = {
  loadSettings: () => Promise<{ settings: EditorialSettings; exists: boolean }>;
  dismissedFindingIds: (itemId: string) => Promise<Set<string>>;
  check: (body: string, section: string | null) => Promise<EditorialCheckResult>;
  suggest: (
    body: string,
    section: string | null,
    target: { finding: EditorialFinding } | { selection: Span },
    note: string | null,
  ) => Promise<RewriteResult>;
  recordFeedback: (input: EditorialFeedbackInput) => Promise<void>;
  /** Ask the server to check one saved version and store the result with it. It skips content it has already checked. */
  checkVersion?: (itemId: string) => Promise<void>;
};
