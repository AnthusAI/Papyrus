/**
 * Unit tests for RendererConfig discriminated union and site-renderer guards.
 *
 *   npx tsx scripts/test-renderer-config.ts
 */
import {
  assertPretextRendererConfig,
  isMarkusRendererConfig,
  isPretextRendererConfig,
  MarkusSiteRendererError,
  type MarkusRendererConfig,
  type PretextRendererConfig,
  type RendererConfig,
} from "../lib/renderer-config";
import { buildDefaultEmptyEditionLayoutPlan } from "../lib/empty-edition-layout-plan";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`FAIL: ${message}`);
}

const pretextConfig: PretextRendererConfig = {
  kind: "pretext",
  layout: "newsprint",
  layoutPlan: buildDefaultEmptyEditionLayoutPlan(),
};

const markusConfig: MarkusRendererConfig = {
  kind: "markus",
  theme: "hackerman",
};

function testTypeGuards() {
  assert(isPretextRendererConfig(pretextConfig), "pretext config recognized");
  assert(!isPretextRendererConfig(markusConfig), "markus config is not pretext");
  assert(isMarkusRendererConfig(markusConfig), "markus config recognized");
  assert(!isMarkusRendererConfig(pretextConfig), "pretext config is not markus");
}

function testAssertPretextRendererConfig() {
  const resolved = assertPretextRendererConfig(pretextConfig);
  assert(resolved.layout === "newsprint", "pretext branch exposes layout");
  assert(resolved.layoutPlan.pages.length >= 1, "pretext branch carries layoutPlan");

  let threw = false;
  try {
    assertPretextRendererConfig(markusConfig);
  } catch (error) {
    threw = true;
    assert(
      error instanceof Error && error.message.includes("markus"),
      "markus config rejected by assertPretextRendererConfig",
    );
  }
  assert(threw, "assertPretextRendererConfig throws for markus");
}

function testExhaustiveSwitch(config: RendererConfig): string {
  switch (config.kind) {
    case "pretext":
      return config.layout;
    case "markus":
      return config.theme;
    default: {
      const _exhaustive: never = config;
      return _exhaustive;
    }
  }
}

function testExhaustiveDiscriminant() {
  assert(testExhaustiveSwitch(pretextConfig) === "newsprint", "pretext switch yields layout");
  assert(testExhaustiveSwitch(markusConfig) === "hackerman", "markus switch yields theme");
}

function testMarkusSiteRendererError() {
  const error = new MarkusSiteRendererError("hackerman", "pilobol-us");
  assert(error.name === "MarkusSiteRendererError", "error name set");
  assert(error.message.includes("pilobol-us"), "error cites site brand");
  assert(error.message.includes("hackerman"), "error cites theme");
  assert(error.message.includes("markus-build"), "error cites static build path");
}

function main() {
  testTypeGuards();
  testAssertPretextRendererConfig();
  testExhaustiveDiscriminant();
  testMarkusSiteRendererError();
  console.log("PASS: renderer-config discriminated union tests");
}

main();
