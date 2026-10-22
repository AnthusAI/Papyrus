import { readFileSync, statSync } from "node:fs";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import { extname, join, normalize, resolve } from "node:path";
import { NextRequest } from "next/server";
import {
  handleNewsletterConfirm,
  handleNewsletterPreferences,
  handleNewsletterState,
  handleNewsletterUnsubscribe,
  type NewsletterApiOptions,
  type NewsletterEvent,
  type NewsletterResult,
} from "../lib/newsletter-api";

/**
 * A stand-in for the CMS app and its CloudFront edge, for browser tests of the newsletter pages: the real route handlers under
 * /api/newsletter/ on a loopback http server, a stub newsletter function behind them, and the site's static files (the projected
 * pages under /newsletter/, the CSS) served from a directory. Like the real edge, an answer of 403 or 404 from a newsletter route
 * becomes the site's 404 page, so a hidden failure shows up as "Page not found". It needs no AWS.
 */
export const MANAGE_TOKEN = "v1.manage.token";
export const CONFIRM_TOKEN = "v1.confirm.token";
const TYPES: Record<string, string> = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2" };

export type Backend = {
  calls: NewsletterEvent[];
  subscribed: Set<string>;
  confirmed: boolean;
  deleted: boolean;
};

export type Harness = { origin: string; backend: Backend; requests: Array<{ method: string; path: string; status: number; origin: string | null }>; close: () => Promise<void> };

const LISTS = [
  { id: "weekly", name: "Weekly roundup", description: "Every Friday." },
  { id: "alerts-x", name: "Alerts", description: "When something ships." },
];
const outputsFor = (siteName: string) => ({
  custom: {
    papyrusPlugins: { newsletter: { contract: 1, fromName: siteName, lists: LISTS.map((list) => ({ ...list, kind: "roundup" })), theme: {} } },
    newsletter: { actionsFunction: "newsletter-fn" },
  },
});

function stubFunction(backend: Backend) {
  return async (_name: string, event: NewsletterEvent): Promise<NewsletterResult> => {
    backend.calls.push(event);
    const ok = (body: Record<string, unknown>) => ({ statusCode: 200, body });
    switch (event.action) {
      case "confirm_page_state":
        return event.token === CONFIRM_TOKEN && !backend.confirmed ? ok({ status: "ready", lists: [LISTS[0]] }) : { statusCode: 410, body: { status: "expired" } };
      case "confirm":
        if (event.token !== CONFIRM_TOKEN || backend.confirmed) return { statusCode: 410, body: { status: "expired" } };
        backend.confirmed = true;
        backend.subscribed = new Set(["weekly"]);
        return ok({ status: "confirmed", lists: [LISTS[0]], manageToken: MANAGE_TOKEN });
      case "preferences_state":
        if (event.token !== MANAGE_TOKEN || backend.deleted) return { statusCode: 400, body: { status: "invalid" } };
        return ok({ status: "ready", email: "r***@example.com", lists: LISTS.map((list) => ({ ...list, subscribed: backend.subscribed.has(list.id) })) });
      case "update_preferences":
        backend.subscribed = new Set(event.lists as string[]);
        return ok({ status: "saved" });
      case "unsubscribe": {
        const names = [...backend.subscribed].map((id) => LISTS.find((list) => list.id === id)).filter(Boolean);
        if (event.list) backend.subscribed.delete(event.list as string);
        else backend.subscribed.clear();
        return ok({ status: "unsubscribed", lists: names });
      }
      case "delete_subscriber":
        backend.deleted = true;
        backend.subscribed.clear();
        return ok({ status: "deleted" });
      default:
        return { statusCode: 400, body: { status: "invalid" } };
    }
  };
}

async function readRequestBody(request: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString("utf8");
}

/** `directory` holds the site's files: `newsletter/<page>/index.html`, `css/…`. `extra` maps more url paths to files. */
export async function startHarness(directory: string, extra: Record<string, string> = {}, siteName = "Fixture Site"): Promise<Harness> {
  const backend: Backend = { calls: [], subscribed: new Set(), confirmed: false, deleted: false };
  const requests: Harness["requests"] = [];
  const root = resolve(directory);
  let origin = "";
  const options = (): NewsletterApiOptions => ({
    environment: { SITE_ENV: "development", NODE_ENV: "test" },
    outputs: outputsFor(siteName),
    invoke: stubFunction(backend),
  });

  const serveFile = (path: string, response: ServerResponse): boolean => {
    const target = extra[path] ?? join(root, normalize(path.endsWith("/") ? `${path}index.html` : path));
    if (!extra[path] && !target.startsWith(root)) return false;
    try {
      if (!statSync(target).isFile()) return false;
      response.writeHead(200, { "content-type": TYPES[extname(target)] ?? "application/octet-stream" });
      response.end(readFileSync(target));
      return true;
    } catch {
      return false;
    }
  };

  const server: Server = createServer(async (incoming, outgoing) => {
    const url = new URL(incoming.url ?? "/", origin);
    const method = incoming.method ?? "GET";
    const record = (status: number) => requests.push({ method, path: url.pathname, status, origin: (incoming.headers.origin as string | undefined) ?? null });
    const notFound = () => {
      const page = serveFileOrNull("404.html");
      record(404);
      outgoing.writeHead(404, { "content-type": "text/html; charset=utf-8" });
      outgoing.end(page ?? "<!doctype html><title>Page not found</title><h1>Page not found</h1>");
    };
    const serveFileOrNull = (name: string) => {
      try {
        return readFileSync(join(root, name));
      } catch {
        return null;
      }
    };
    try {
      if (url.pathname.startsWith("/api/newsletter/")) {
        const body = method === "GET" || method === "HEAD" ? undefined : await readRequestBody(incoming);
        const headers = new Headers();
        for (const [name, value] of Object.entries(incoming.headers)) if (value !== undefined && !["content-length", "host", "connection", "transfer-encoding"].includes(name)) headers.set(name, Array.isArray(value) ? value.join(", ") : value);
        const request = new NextRequest(url, { method, headers, ...(body === undefined ? {} : { body }) });
        const handler =
          url.pathname === "/api/newsletter/confirm" ? handleNewsletterConfirm
          : url.pathname === "/api/newsletter/preferences" ? handleNewsletterPreferences
          : url.pathname === "/api/newsletter/unsubscribe" ? handleNewsletterUnsubscribe
          : url.pathname === "/api/newsletter/state" ? handleNewsletterState
          : null;
        if (!handler) return notFound();
        const answer = await handler(request, options());
        // The real edge swaps an origin answer of 403 or 404 for the site's 404 page.
        if (answer.status === 403 || answer.status === 404) return notFound();
        const text = await answer.text();
        const responseHeaders: Record<string, string> = {};
        answer.headers.forEach((value: string, name: string) => (responseHeaders[name] = value));
        record(answer.status);
        outgoing.writeHead(answer.status, responseHeaders);
        return outgoing.end(text);
      }
      if (method === "GET" && serveFile(url.pathname, outgoing)) return void record(200);
      notFound();
    } catch (error) {
      record(500);
      outgoing.writeHead(500);
      outgoing.end(String(error));
    }
  });
  await new Promise<void>((done) => server.listen(0, done));
  origin = `http://localhost:${(server.address() as AddressInfo).port}`;
  return {
    origin,
    backend,
    requests,
    close: () => new Promise<void>((done) => server.close(() => done())),
  };
}
