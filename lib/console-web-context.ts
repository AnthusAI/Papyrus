import type { PapyrusWebUiContext } from "./papyrus-web-locations";

export const CONSOLE_WEB_CONTEXT_MESSAGE_KIND = "console_web_context";

export type ConsoleWebContextEvent = "session_start" | "navigation";

export type FormattedConsoleWebContext = {
  visibleContent: string;
  summary: string;
  agentInstructions: string;
};

export function webUiContextKey(webUi: PapyrusWebUiContext): string {
  return [
    webUi.papyrusLocationUri,
    webUi.webPath,
    webUi.papyrusObjectUri ?? "",
    webUi.viewMode ?? "",
  ].join("|");
}

export function formatConsoleWebContextMessage(
  webUi: PapyrusWebUiContext,
  event: ConsoleWebContextEvent,
): FormattedConsoleWebContext {
  const locationUri = webUi.papyrusLocationUri.trim();
  const webPath = webUi.webPath.trim();
  const objectUri = webUi.papyrusObjectUri?.trim() ?? "";
  const label = webUi.label?.trim() ?? "";
  const tab = webUi.newsroomTab?.trim() ?? "";
  const viewMode = webUi.viewMode?.trim() ?? "";

  const headline = event === "session_start"
    ? "Console session started on this page."
    : "You navigated to a new page in the newsroom.";

  const visibleLines = [
    headline,
    "",
    locationUri ? `Papyrus location: ${locationUri}` : null,
    webPath ? `Web path: ${webPath}` : null,
    objectUri ? `Focused object: ${objectUri}` : null,
    label ? `Label: ${label}` : null,
    tab ? `Desk: ${tab}` : null,
    viewMode ? `View: ${viewMode}` : null,
  ].filter((line): line is string => Boolean(line));

  const agentLines = [
    "Papyrus web UI context for this console thread:",
    locationUri ? `- papyrus_location_uri: ${locationUri}` : null,
    webPath ? `- web_path: ${webPath}` : null,
    objectUri ? `- focused_object_uri: ${objectUri}` : null,
    label ? `- label: ${label}` : null,
    viewMode ? `- view_mode: ${viewMode}` : null,
    tab ? `- newsroom_tab: ${tab}` : null,
    "",
    "Use execute_tactus with papyrus.web.current_location{} to re-read this snapshot.",
    "Use papyrus.web.navigate{ uri = \"papyrus://...\" } to move the browser when appropriate.",
  ].filter((line): line is string => line !== null);

  if (objectUri.startsWith("papyrus://reference/")) {
    const referenceId = objectUri.slice("papyrus://reference/".length).trim();
    if (referenceId) {
      agentLines.push(
        "",
        `The user is viewing reference detail (${referenceId}). For questions about "this reference", the open page, or what they are looking at, do not ask them to paste the reference.`,
        `Call execute_tactus with Reference.get{ id = "${referenceId}" } (lineage ids from the URL resolve to the current version), then use listReferenceAttachments or knowledge tools as needed.`,
        "If extracted text attachments exist, read them via storage paths or anchored knowledge query — catalog metadata alone is not enough to discuss paper contents.",
      );
    }
  }

  const summaryParts = [label, tab, viewMode === "detail" ? "detail" : "index"].filter(Boolean);
  return {
    visibleContent: visibleLines.join("\n"),
    summary: summaryParts.length
      ? `Page context: ${summaryParts.join(" · ")}`
      : "Page context updated",
    agentInstructions: agentLines.join("\n"),
  };
}

export function readConsoleAgentInstructionsFromMessageMetadata(metadata: unknown): string | null {
  if (!metadata || typeof metadata !== "object") return null;
  const record = metadata as Record<string, unknown>;
  const consoleMeta = record.console;
  if (!consoleMeta || typeof consoleMeta !== "object") return null;
  const instructions = (consoleMeta as Record<string, unknown>).agentInstructions;
  return typeof instructions === "string" && instructions.trim() ? instructions.trim() : null;
}

export function readConsoleWebUiFromMessageMetadata(metadata: unknown): PapyrusWebUiContext | null {
  if (!metadata || typeof metadata !== "object") return null;
  const record = metadata as Record<string, unknown>;
  const consoleMeta = record.console;
  if (!consoleMeta || typeof consoleMeta !== "object") return null;
  const webUi = (consoleMeta as Record<string, unknown>).webUi;
  if (!webUi || typeof webUi !== "object") return null;
  const entry = webUi as Record<string, unknown>;
  const webPath = typeof entry.webPath === "string" ? entry.webPath : "";
  const papyrusLocationUri = typeof entry.papyrusLocationUri === "string" ? entry.papyrusLocationUri : "";
  if (!webPath && !papyrusLocationUri) return null;
  return {
    webPath,
    papyrusLocationUri,
    papyrusObjectUri: typeof entry.papyrusObjectUri === "string" ? entry.papyrusObjectUri : null,
    newsroomTab: typeof entry.newsroomTab === "string" ? entry.newsroomTab : null,
    viewMode: entry.viewMode === "index" || entry.viewMode === "detail" ? entry.viewMode : null,
    indexFilters: entry.indexFilters && typeof entry.indexFilters === "object"
      ? Object.fromEntries(
        Object.entries(entry.indexFilters as Record<string, unknown>)
          .filter(([, value]) => typeof value === "string" && value.trim()),
      ) as Record<string, string>
      : null,
    label: typeof entry.label === "string" ? entry.label : null,
  };
}
