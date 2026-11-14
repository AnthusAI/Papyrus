export const PUBLIC_HANDLE_MINIMUM_LENGTH = 3;
export const PUBLIC_HANDLE_MAXIMUM_LENGTH = 24;
export const PUBLIC_HANDLE_CHARACTERS = /^[a-z0-9-]*$/;
export const PUBLIC_HANDLE_PATTERN = /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/;
export const PUBLIC_HANDLE_RESERVED = ["admin", "editor", "ai", "papyrus", "anonymous"] as const;

export type PublicHandleRefusal = "length" | "characters" | "at-sign" | "reserved";

export type PublicHandleCheck =
  | { valid: true; handle: string }
  | { valid: false; reason: PublicHandleRefusal };

export function normalizePublicHandle(value: string): string {
  return value.trim().toLowerCase();
}

export function checkPublicHandle(value: string): PublicHandleCheck {
  const handle = normalizePublicHandle(value);
  if (handle.includes("@")) return { valid: false, reason: "at-sign" };
  if (!PUBLIC_HANDLE_CHARACTERS.test(handle)) return { valid: false, reason: "characters" };
  if (handle.length < PUBLIC_HANDLE_MINIMUM_LENGTH || handle.length > PUBLIC_HANDLE_MAXIMUM_LENGTH) return { valid: false, reason: "length" };
  if (!PUBLIC_HANDLE_PATTERN.test(handle)) return { valid: false, reason: "characters" };
  if ((PUBLIC_HANDLE_RESERVED as readonly string[]).includes(handle)) return { valid: false, reason: "reserved" };
  return { valid: true, handle };
}

export const PUBLIC_HANDLE_TAKEN_MESSAGE = "That handle is taken";
export const PUBLIC_HANDLE_RULE_MESSAGE = "3 to 24 letters, digits and hyphens";
export const PUBLIC_HANDLE_RESERVED_MESSAGE = "That handle is reserved";

export function publicHandleRefusalMessage(reason: PublicHandleRefusal): string {
  return reason === "reserved" ? PUBLIC_HANDLE_RESERVED_MESSAGE : PUBLIC_HANDLE_RULE_MESSAGE;
}
