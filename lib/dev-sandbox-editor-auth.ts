export type DevSandboxEditorAuth = {
  username: string;
  password: string;
};

const DEFAULT_SEED_USERNAME = "papyrus-seed-editor@example.com";
const DEFAULT_SEED_PASSWORD = "PapyrusSeed1!";

export function resolveDevSandboxEditorAuth(): DevSandboxEditorAuth | null {
  if (process.env.NODE_ENV !== "development") return null;
  if (process.env.PAPYRUS_DEV_SEED_SIGNIN === "0") return null;

  const username = process.env.PAPYRUS_SEED_USERNAME?.trim() || DEFAULT_SEED_USERNAME;
  const password = process.env.PAPYRUS_SEED_PASSWORD?.trim() || DEFAULT_SEED_PASSWORD;
  if (!username || !password) return null;

  return { username, password };
}
