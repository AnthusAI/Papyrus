export type NewsroomChatFetch = typeof fetch;

export function createNewsroomChatFetch(
  accessToken: () => Promise<string | null>,
  fetcher: NewsroomChatFetch,
): NewsroomChatFetch {
  return async (input, init) => {
    if (typeof input !== "string" || (!input.startsWith("/api/newsroom/chat/") && !input.startsWith("/api/auth/prospectus/"))) {
      throw new Error("Newsroom credentials can only be sent to this site's chat identity routes.");
    }
    const token = await accessToken();
    if (!token) throw new Error("sign_in_required");
    const headers = new Headers(init?.headers);
    headers.set("authorization", `Bearer ${token}`);
    return fetcher(input, { ...init, headers, credentials: "same-origin", cache: "no-store" });
  };
}

export const newsroomChatFetch: NewsroomChatFetch = createNewsroomChatFetch(async () => {
  const { fetchAuthSession } = await import("aws-amplify/auth");
  const session = await fetchAuthSession();
  return session.tokens?.accessToken?.toString() ?? null;
}, (input, init) => globalThis.fetch(input, init));

export async function connectNewsroomChat(returnPath: string, fetcher: NewsroomChatFetch = newsroomChatFetch): Promise<string> {
  const response = await fetcher(`/api/auth/prospectus/sign-in?newsroomChat=true&returnTo=${encodeURIComponent(returnPath)}`, { method: "POST" });
  const body = await response.json() as { authorizationUrl?: string; message?: string };
  if (!response.ok || !body.authorizationUrl) throw new Error(body.message ?? "Private chat could not connect to your publishing account.");
  return body.authorizationUrl;
}
