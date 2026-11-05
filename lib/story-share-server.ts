import { generateServerClientUsingCookies } from "@aws-amplify/adapter-nextjs/api";
import { fetchAuthSession } from "aws-amplify/auth/server";
import { generateClient } from "aws-amplify/data";
import { cookies } from "next/headers";
import type { Schema } from "../amplify/data/resource";
import { getAmplifyServerRuntime, runWithGuestAmplifyContext } from "./amplify-server-runtime";

/** True when the request carries a newsroom session. Only used to pick which identity asks; the function decides what that identity may see. */
async function hasSession(): Promise<boolean> {
  const { runWithAmplifyServerContext } = getAmplifyServerRuntime();
  try {
    return await runWithAmplifyServerContext({
      nextServerContext: { cookies },
      operation: async (contextSpec) => Boolean((await fetchAuthSession(contextSpec)).tokens?.idToken),
    });
  } catch {
    return false;
  }
}

type ShareQuery = "viewStoryShare" | "viewStoryShareMedia";

async function ask(query: ShareQuery, input: Record<string, unknown>, mode: "userPool" | "identityPool"): Promise<unknown> {
  const argument = { input: JSON.stringify(input) };
  const response =
    mode === "userPool"
      ? await generateServerClientUsingCookies<Schema>({ config: getAmplifyServerRuntime().config, cookies, authMode: "userPool" }).queries[query](argument)
      : await runWithGuestAmplifyContext(() => generateClient<Schema>({ authMode: "identityPool" }).queries[query](argument));
  if (response.errors && response.errors.length > 0) throw new Error("The newsroom did not answer.");
  return response.data;
}

/**
 * Asks the newsroom's function what a link shows. A visitor with a session asks as themselves, which is how a signed-in link recognises them; everyone else asks as a guest.
 * The token travels in the request body to the function and is never logged here. Any failure is the caller's "not available".
 */
export async function askStoryShare(query: ShareQuery, input: Record<string, unknown>): Promise<unknown> {
  if (await hasSession()) {
    try {
      return await ask(query, input, "userPool");
    } catch {
      // An expired session asks again as a guest: the function then says "sign in" for a signed-in link.
    }
  }
  return ask(query, input, "identityPool");
}
