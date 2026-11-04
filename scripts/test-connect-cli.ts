/** Acceptance for the "Connect the CLI or an agent" page: synthetic sites only, fixture origin, no network, 375 and 1440 pixels. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { NextRequest } from "next/server";
import { cliConnectPlan, CLI_INSTALL_COMMAND } from "../lib/cli-connect";
import { readCliLoginDocument, type AmplifyOutputsForCliLogin } from "../lib/cli-login-discovery";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://connect-cli.test";
const site = "https://newsroom.example.test";

const outputsMain: AmplifyOutputsForCliLogin = {
  auth: { user_pool_id: "synthetic-pool", user_pool_client_id: "synthetic-web-client", aws_region: "us-east-1",
    oauth: { domain: "synthetic.auth.us-east-1.amazoncognito.com", redirect_sign_in_uri: [`${site}/`, "http://localhost:3001/", `${site}/cli/callback`] } },
  data: { url: "https://synthetic.appsync-api.us-east-1.amazonaws.com/graphql" },
};
const withRemote: AmplifyOutputsForCliLogin = { ...outputsMain, custom: { cliLogin: { brokerEndpoint: "https://synthetic.lambda-url.us-east-1.on.aws/", remoteCallbackUri: `${site}/cli/callback` } } };
const planFor = (outputs: AmplifyOutputsForCliLogin | null, environment: Record<string, string | undefined> = { PAPYRUS_SITE_ORIGIN: site }) =>
  cliConnectPlan(readCliLoginDocument(new NextRequest("http://internal.invalid/"), { readOutputs: () => outputs, environment }));

let bundle: Promise<string> | undefined;
let css: Promise<string> | undefined;
const tailwind = () => (css ??= (async () => {
  const file = `${root}app/tailwind.css`;
  const { default: postcss } = await import("postcss");
  const { default: tw } = await import("@tailwindcss/postcss");
  return (await postcss([tw() as never]).process(fs.readFileSync(file, "utf8"), { from: file })).css;
})());
const script = () => (bundle ??= build({
  absWorkingDir: root, bundle: true, write: false, platform: "browser", jsx: "automatic", logLevel: "silent",
  define: { "process.env.NODE_ENV": '"development"' }, banner: { js: 'window.process = { env: { NODE_ENV: "development" } };' },
  stdin: { resolveDir: root, loader: "tsx", sourcefile: "connect-cli-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { ConnectCliBody } from "./components/connect-cli-body";
const plan = JSON.parse(new URLSearchParams(location.search).get("plan") || "null");
createRoot(document.getElementById("root")).render(<div className="newsroom-organizer"><ConnectCliBody plan={plan} /></div>);` },
}).then((result) => result.outputFiles[0].text));

async function open(plan: unknown, width: number, scheme: "light" | "dark" = "light", shot?: string) {
  const [js, tw] = [await script(), await tailwind()];
  const organizer = fs.readFileSync(`${root}components/newsroom-organizer.css`, "utf8");
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width, height: 1400 }, colorScheme: scheme });
  const page = await context.newPage();
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  // The fixture origin is not a secure context, so the clipboard is a recorder.
  await page.addInitScript("window.copied = []; Object.defineProperty(navigator, 'clipboard', { value: { writeText: async (text) => { window.copied.push(text); } } });");
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript; charset=utf-8", body: js });
    const ink = scheme === "dark" ? "#f1f1ea" : "#1c2420";
    const paper = scheme === "dark" ? "#131815" : "#f7f4ec";
    return route.fulfill({ contentType: "text/html", body: `<html><head><meta name="viewport" content="width=device-width"><style>${tw}</style><style>${organizer}</style><style>:root{--org-ink:${ink};--org-muted:${ink}b0;--org-paper:${paper}}body{margin:0;background:${paper};font:16px sans-serif;padding:16px}.newsroom-organizer{display:block;height:auto;max-height:none;overflow:visible}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/?plan=${encodeURIComponent(JSON.stringify(plan))}`);
  await page.waitForSelector("[data-connect-cli], [data-connect-unavailable]");
  if (shot) await page.screenshot({ path: shot, fullPage: true });
  return { browser, page, errors };
}

async function each(plan: unknown, body: (page: Page, width: number) => Promise<void>) {
  for (const width of [375, 1440]) for (const scheme of ["light", "dark"] as const) {
    const { browser, page, errors } = await open(plan, width, scheme);
    try { await body(page, width); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), true, "no sideways scroll"); assert.deepEqual(errors, []); }
    finally { await browser.close(); }
  }
}

const scenarios: Record<string, () => Promise<void>> = {
  /** The commands come from the discovery values and the site's own origin, never typed. */
  async commands() {
    const plan = planFor(withRemote)!;
    assert.equal(plan.browserCommand, "papyrus login newsroom.example.test");
    assert.equal(plan.remoteCommand, "papyrus login --remote newsroom.example.test");
    assert.equal(plan.install, CLI_INSTALL_COMMAND);
    // A console on its own host is the address the file names, so the commands name it too.
    assert.equal(planFor(withRemote, { PAPYRUS_SITE_ORIGIN: site, PAPYRUS_CONSOLE_ORIGIN: "https://console.example.test" })!.remoteCommand, null, "the broker names the site origin, not the console host, so remote is not offered there");
    assert.equal(planFor(outputsMain, { PAPYRUS_SITE_ORIGIN: site, PAPYRUS_CONSOLE_ORIGIN: "https://console.example.test" })!.browserCommand, "papyrus login console.example.test");
    assert.equal(planFor({ ...outputsMain, auth: { ...outputsMain.auth, oauth: { domain: "x", redirect_sign_in_uri: [] } } }), null, "a site that does not publish the file gets no commands");
  },
  /** Remote is offered only when the discovery values name a broker. */
  async remote() {
    assert.equal(planFor(outputsMain)!.remoteCommand, null);
    await each(planFor(withRemote), async (page) => {
      assert.deepEqual(await page.locator("[data-connect-command]").allInnerTexts(), ["pipx install papyrus-newsroom", "papyrus login newsroom.example.test", "papyrus login --remote newsroom.example.test", "papyrus whoami newsroom.example.test"]);
      assert.equal(await page.locator("[data-connect-remote-unavailable]").count(), 0);
      assert.ok((await page.locator("[data-connect-remote-warning]").innerText()).includes("Open the link yourself"));
    });
    await each(planFor(outputsMain), async (page) => {
      assert.deepEqual(await page.locator("[data-connect-command]").allInnerTexts(), ["pipx install papyrus-newsroom", "papyrus login newsroom.example.test", "papyrus whoami newsroom.example.test"]);
      assert.ok((await page.locator("[data-connect-remote-unavailable]").innerText()).includes("not switched on"));
    });
    await each(null, async (page) => {
      assert.equal(await page.locator("[data-connect-command]").count(), 0);
      assert.ok((await page.locator("[data-connect-unavailable]").innerText()).includes("not set up"));
    });
  },
  /** Each command has a copy button that copies exactly it and says so in words and an icon change. */
  async copy() {
    await each(planFor(withRemote), async (page) => {
      const buttons = page.locator("[data-connect-copy]");
      assert.equal(await buttons.count(), 4);
      await buttons.nth(2).click();
      assert.deepEqual(await page.evaluate(() => (window as unknown as { copied: string[] }).copied), ["papyrus login --remote newsroom.example.test"]);
      assert.equal((await buttons.nth(2).innerText()).trim(), "Copied");
      assert.equal(await buttons.nth(2).locator("svg.lucide-check").count(), 1);
      assert.equal(await buttons.nth(1).locator("svg.lucide-copy").count(), 1);
    });
  },
  /** Flat tones and rounded rectangles: no visible border, outline or rule; buttons, not drop-downs; Lucide icons. */
  async design() {
    await each(planFor(withRemote), async (page) => {
      const offenders = await page.locator("[data-connect-cli], [data-connect-cli] *").evaluateAll((elements) => elements.filter((element) => {
        const style = getComputedStyle(element);
        const edge = ["top", "right", "bottom", "left"].some((side) => parseFloat(style.getPropertyValue(`border-${side}-width`)) > 0 && style.getPropertyValue(`border-${side}-style`) !== "none" && !/rgba\(\d+, \d+, \d+, 0\)|transparent/.test(style.getPropertyValue(`border-${side}-color`)));
        return edge || (style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0) || style.boxShadow !== "none";
      }).map((element) => element.tagName + "." + element.className));
      assert.deepEqual(offenders, []);
      assert.equal(await page.locator("select, [role=combobox], [role=listbox]").count(), 0);
      assert.ok(await page.locator("svg.lucide").count() >= 5);
      assert.equal(await page.locator("[data-connect-cli] svg:not(.lucide)").count(), 0);
      const radius = await page.locator("[data-connect-step]").first().evaluate((element) => parseFloat(getComputedStyle(element).borderTopLeftRadius));
      assert.ok(radius >= 8);
    });
  },
  /** The words an editor reads: plain, accurate, and "Account"-safe. */
  async prose() {
    await each(planFor(withRemote), async (page) => {
      const text = await page.locator("[data-connect-cli]").innerText();
      assert.ok(text.includes("acts as you"));
      assert.ok(text.includes("nothing more"));
      assert.ok(text.includes("papyrus logout newsroom.example.test"));
      assert.ok(!/organization/i.test(text) && !/\bdesk\b/i.test(text));
    });
  },
  /** Screenshots for review when CONNECT_SHOTS names a directory. */
  async shots() {
    const dir = process.env.CONNECT_SHOTS;
    if (!dir) return;
    fs.mkdirSync(dir, { recursive: true });
    for (const [name, plan] of [["remote-on", planFor(withRemote)], ["remote-off", planFor(outputsMain)], ["not-set-up", null]] as const) for (const width of [375, 1440]) for (const scheme of ["light", "dark"] as const) {
      const { browser } = await open(plan, width, scheme, `${dir}/harness-${name}-${width}-${scheme}.png`);
      await browser.close();
    }
  },
};

async function main() {
  const requested = process.argv[2];
  for (const [name, scenario] of Object.entries(scenarios)) {
    if (requested && requested !== name) continue;
    await scenario();
    console.log(`Connect CLI scenario passed: ${name}`);
  }
}
main().catch((error) => { console.error(error); process.exit(1); });
