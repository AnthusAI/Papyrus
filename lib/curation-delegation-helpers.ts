export const DEFAULT_DELEGATION_HOURS = 8;
export const MINIMUM_DELEGATION_HOURS = 1;
export const MAXIMUM_DELEGATION_HOURS = 72;

export type CurationDelegationRecord = {
  delegationId: string;
  agentLabel: string;
  grantorLabel: string | null;
  expiresAt: string;
  revokedAt: string | null;
};

export type DelegationInputValidation =
  | { ok: true; agentLabel: string; hours: number }
  | { ok: false; message: string };

export function validateDelegationInput(agentLabelText: string, hoursText: string): DelegationInputValidation {
  const agentLabel = agentLabelText.trim();
  if (!agentLabel) return { ok: false, message: "Enter the name of the agent you are trusting." };
  if (/\s/.test(agentLabel)) return { ok: false, message: "The agent name cannot contain spaces. Use the name the agent passes as --agent." };
  const trimmedHours = hoursText.trim();
  if (!/^\d+$/.test(trimmedHours)) return { ok: false, message: `Enter a whole number of hours from ${MINIMUM_DELEGATION_HOURS} to ${MAXIMUM_DELEGATION_HOURS}.` };
  const hours = Number(trimmedHours);
  if (hours < MINIMUM_DELEGATION_HOURS || hours > MAXIMUM_DELEGATION_HOURS) {
    return { ok: false, message: `A delegation lasts from ${MINIMUM_DELEGATION_HOURS} to ${MAXIMUM_DELEGATION_HOURS} hours.` };
  }
  return { ok: true, agentLabel, hours };
}

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

export function buildDelegatedCommandLine(input: { email: string; agentLabel: string; token: string; action?: "approve" | "reject" }): string {
  const email = input.email.trim() || "<your-email>";
  return `papyrus references ${input.action ?? "approve"} <reference-id> --on-behalf-of ${email} --agent ${input.agentLabel} --instruction "<the person's own words>" --delegation-token ${input.token}`;
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
