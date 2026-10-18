export interface ProspectusPublishingAccountChoice {
  accountId: string;
  name?: string;
  role: string;
}

export type ProspectusAccountState =
  | { status: "unavailable" }
  | { status: "signedOut"; signInUrl: string }
  | {
      status: "signedIn";
      publishingAccounts: ProspectusPublishingAccountChoice[];
      selectedAccountId: string | null;
      cyclotronLabAccess: boolean;
    };

type FetchImplementation = (input: string, init?: RequestInit) => Promise<Response>;

const SESSION_PATH = "/api/auth/prospectus/session";
const SELECTION_PATH = "/api/auth/prospectus/selection";
const SIGN_IN_PATH = "/api/auth/prospectus/sign-in";

export function prospectusSignInUrl(returnPath: string): string {
  return `${SIGN_IN_PATH}?returnTo=${encodeURIComponent(returnPath)}`;
}

export async function loadProspectusAccountState(
  returnPath: string,
  fetchImplementation: FetchImplementation = fetch,
): Promise<ProspectusAccountState> {
  let response: Response;
  try {
    response = await fetchImplementation(SESSION_PATH, { credentials: "same-origin", cache: "no-store" });
  } catch {
    return { status: "unavailable" };
  }
  if (!response.ok) return { status: "unavailable" };
  const body = await response.json().catch(() => null) as
    | { signedIn?: boolean; publishingAccounts?: ProspectusPublishingAccountChoice[]; selectedAccountId?: string | null; cyclotronLabAccess?: boolean }
    | null;
  if (!body) return { status: "unavailable" };
  if (!body.signedIn) return { status: "signedOut", signInUrl: prospectusSignInUrl(returnPath) };
  return {
    status: "signedIn",
    publishingAccounts: Array.isArray(body.publishingAccounts) ? body.publishingAccounts : [],
    selectedAccountId: body.selectedAccountId ?? null,
    cyclotronLabAccess: body.cyclotronLabAccess === true,
  };
}

export async function selectProspectusAccount(
  accountId: string,
  fetchImplementation: FetchImplementation = fetch,
): Promise<{ selectedAccountId: string; role: string } | { error: string }> {
  const response = await fetchImplementation(SELECTION_PATH, {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ accountId }),
  });
  const body = await response.json().catch(() => null) as { selectedAccountId?: string; role?: string; message?: string } | null;
  if (!response.ok || !body?.selectedAccountId) return { error: body?.message ?? "That account could not be selected." };
  return { selectedAccountId: body.selectedAccountId, role: body.role ?? "" };
}
