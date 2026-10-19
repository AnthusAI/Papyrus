export type CurationDelegationState = "pending" | "approved" | "denied" | "expired" | "revoked";

export type CurationDelegationRecord = {
  delegationId: string;
  agentLabel: string;
  grantorLabel: string | null;
  expiresAt: string;
  revokedAt: string | null;
  state?: CurationDelegationState | null;
  /** XXXX-XXXX, present only while the request is pending. */
  userCode?: string | null;
  requestedHours?: number | null;
  pendingExpiresAt?: string | null;
  approvedAt?: string | null;
  deniedAt?: string | null;
};

export function delegationExpiryText(expiresAt: string, revokedAt: string | null, nowMilliseconds: number): string {
  if (revokedAt) return "Revoked";
  const remaining = Date.parse(expiresAt) - nowMilliseconds;
  if (!Number.isFinite(remaining) || remaining <= 0) return "Expired";
  const minutes = Math.ceil(remaining / 60_000);
  if (minutes < 60) return `Expires in ${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
  const hours = Math.round(remaining / 3_600_000);
  return `Expires in ${hours} ${hours === 1 ? "hour" : "hours"}`;
}

export function isDelegationActive(record: CurationDelegationRecord, nowMilliseconds: number): boolean {
  return !record.revokedAt && Date.parse(record.expiresAt) > nowMilliseconds;
}

export function describeDelegationError(error: unknown): string {
  const raw = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  const graphql = (error as { errors?: Array<{ message?: string }> } | null)?.errors?.[0]?.message ?? "";
  const text = `${raw} ${graphql}`.toLowerCase();
  if (text.includes("not authorized") || text.includes("unauthorized")) return "Your account is not allowed to manage delegations. Only editors and administrators can.";
  if (text.includes("not found")) return "That delegation no longer exists.";
  if (text.includes("only the person who granted")) return "Only the person who granted a delegation, or an administrator, can revoke it.";
  if (text.includes("network") || text.includes("failed to fetch")) return "Could not reach the server. Check your connection and try again.";
  const detail = (graphql || raw).trim();
  return detail ? `The server refused the request: ${detail}` : "Something went wrong. Nothing was changed.";
}

/** A pending request that an agent started and nobody has approved, denied or let lapse. */
export function isPendingDelegation(record: CurationDelegationRecord, nowMilliseconds: number): boolean {
  return record.state === "pending" && Boolean(record.userCode) && Date.parse(record.pendingExpiresAt ?? record.expiresAt) > nowMilliseconds;
}

/** "9:41 left" for a request that is still open, "Expired" once its window has passed. */
export function pendingCountdownText(pendingExpiresAt: string | null | undefined, nowMilliseconds: number): string {
  const remaining = Date.parse(pendingExpiresAt ?? "") - nowMilliseconds;
  if (!Number.isFinite(remaining) || remaining <= 0) return "Expired";
  const totalSeconds = Math.ceil(remaining / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")} left`;
}

/** The state of a decided or lapsed delegation in words an editor reads in the list. */
export function delegationStateText(record: CurationDelegationRecord, nowMilliseconds: number): string {
  if (record.state === "denied") return "Denied";
  if (record.state === "pending") return pendingCountdownText(record.pendingExpiresAt ?? record.expiresAt, nowMilliseconds) === "Expired" ? "Request expired" : "Waiting for a decision";
  return delegationExpiryText(record.expiresAt, record.revokedAt, nowMilliseconds);
}

export function requestedHoursText(hours: number | null | undefined): string {
  if (!hours || hours <= 0) return "Duration not stated";
  return `Asks for ${hours} ${hours === 1 ? "hour" : "hours"}`;
}
