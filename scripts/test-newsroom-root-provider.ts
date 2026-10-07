/**
 * The root-mounted newsroom must render inside NewsDeskClientProvider, exactly like /newsroom/* does through its layout.
 * Without the provider the access gate never leaves "checking" (no Cognito or AppSync request is ever made).
 *
 *   PAPYRUS_SITE_BRAND=pilobol-us npx tsx scripts/test-newsroom-root-provider.ts
 */
import assert from "node:assert/strict";
import Module from "node:module";
import * as React from "react";
import type { ReactElement } from "react";

(globalThis as { React?: unknown }).React = React;

type ModuleWithLoad = { _load: (request: string, ...rest: unknown[]) => unknown };
const moduleInternals = Module as unknown as ModuleWithLoad;
const loadModule = moduleInternals._load;
moduleInternals._load = function loadWithServerOnlyStub(this: unknown, request: string, ...rest: unknown[]) {
  if (request === "server-only" || request === "papyrus-amplify-outputs") return {};
  return loadModule.call(this, request, ...rest);
};

async function run() {
  const { default: Home } = await import("../app/page");
  const { default: NewsDeskRootPage } = await import("../app/newsroom/page");
  const { default: NewsroomLayout } = await import("../app/newsroom/layout");
  const { NewsroomClientShell } = await import("../components/newsroom-client-shell");
  const { NewsDeskClientProvider } = await import("../components/news-desk-client-provider");

  const rootElement = (await Home({ searchParams: Promise.resolve({}) })) as ReactElement<{ children: ReactElement }>;
  assert.equal(rootElement.type, NewsroomClientShell, "root page must be wrapped in NewsroomClientShell");
  assert.equal(rootElement.props.children.type, NewsDeskRootPage, "the shell must wrap the newsroom root page");

  const layoutElement = NewsroomLayout({ children: null }) as ReactElement;
  assert.equal(layoutElement.type, NewsroomClientShell, "the /newsroom layout must use the same shell");

  const shellElement = NewsroomClientShell({ children: null }) as ReactElement;
  assert.equal(shellElement.type, NewsDeskClientProvider, "the shell must render NewsDeskClientProvider");

  console.log("newsroom root provider tests passed");
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
