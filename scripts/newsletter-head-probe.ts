// Sends one HEAD request to a legacy newsletter route handler and prints what a mail scanner would see. Used by the
// "mail scanner's HEAD request" backend scenario; the invoker records every call so the scenario can prove none was made.
import { NextRequest } from "next/server";
import { handleNewsletterConfirm, handleNewsletterPreferences, handleNewsletterUnsubscribe } from "../lib/newsletter-api";

const [route, token] = process.argv.slice(2);
const handlers = { confirm: handleNewsletterConfirm, preferences: handleNewsletterPreferences, unsubscribe: handleNewsletterUnsubscribe } as const;
const handler = handlers[route as keyof typeof handlers];
if (!handler) throw new Error(`unknown route ${route}`);
const calls: unknown[] = [];
(async () => {
const response = await handler(new NextRequest(new URL(`/api/newsletter/${route}?t=${token}`, "https://localhost:3000"), { method: "HEAD" }), {
  environment: { PAPYRUS_SITE_ORIGIN: "https://news.example.com", SITE_ENV: "production" },
  outputs: { custom: { papyrusPlugins: { newsletter: { contract: 1, fromName: "Example News", lists: [{ id: "weekly", name: "Weekly roundup", description: "", kind: "roundup" }], theme: { accent: "#aa3300", text: "#111111", background: "#ffffff" } } }, newsletter: { actionsFunction: "newsletter-fn" } } },
  invoke: async (_name: string, event: unknown) => {
    calls.push(event);
    throw new Error("a HEAD request must not reach the function");
  },
});
const location = new URL(response.headers.get("location") ?? "", "https://news.example.com");
console.log(JSON.stringify({ status: response.status, path: location.pathname, body: await response.text(), calls: calls.length }));
})();
