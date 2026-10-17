import assert from "node:assert/strict";
import { prepareWithSegments, layoutNextLine, clearPretextMeasurementCache } from "../lib/pretext-layout";
import { watchBrandFontsLoaded, type FontFaceSetLike } from "../lib/brand-fonts-watch";

function createFakeFontFaceSet() {
  const listeners = new Map<string, Set<() => void>>();
  let resolveLoad: () => void = () => undefined;
  const loadGate = new Promise<void>((resolve) => {
    resolveLoad = resolve;
  });
  const fontFaceSet: FontFaceSetLike = {
    load: () => loadGate,
    ready: loadGate,
    addEventListener: (type, listener) => {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type)?.add(listener);
    },
    removeEventListener: (type, listener) => listeners.get(type)?.delete(listener),
  };
  return {
    fontFaceSet,
    finishLoading: resolveLoad,
    emit: (type: string) => listeners.get(type)?.forEach((listener) => listener()),
    listenerCount: (type: string) => listeners.get(type)?.size ?? 0,
  };
}

async function flushMicrotasks() {
  for (let turn = 0; turn < 5; turn += 1) await Promise.resolve();
}

async function main() {
  assert.doesNotThrow(() => clearPretextMeasurementCache());
  assert.equal(typeof prepareWithSegments, "function");
  assert.equal(typeof layoutNextLine, "function");

  const noFonts: string[] = [];
  const stopNoFonts = watchBrandFontsLoaded({
    fontFaceSet: createFakeFontFaceSet().fontFaceSet,
    families: [],
    clearMeasurementCaches: () => noFonts.push("clear"),
    onFontsSettled: () => noFonts.push("settled"),
  });
  await flushMicrotasks();
  stopNoFonts();
  assert.deepEqual(noFonts, [], "brands without fonts never clear or notify");

  const serverEvents: string[] = [];
  watchBrandFontsLoaded({
    fontFaceSet: undefined,
    families: ["Inter"],
    clearMeasurementCaches: () => serverEvents.push("clear"),
    onFontsSettled: () => serverEvents.push("settled"),
  })();
  assert.deepEqual(serverEvents, [], "server rendering has no FontFaceSet and does nothing");

  const fake = createFakeFontFaceSet();
  const events: string[] = [];
  const stop = watchBrandFontsLoaded({
    fontFaceSet: fake.fontFaceSet,
    families: ["Inter", "IBM Plex Serif"],
    clearMeasurementCaches: () => events.push("clear"),
    onFontsSettled: () => events.push("settled"),
  });
  await flushMicrotasks();
  assert.deepEqual(events, [], "nothing happens before fonts load");
  fake.finishLoading();
  await flushMicrotasks();
  assert.deepEqual(events, ["clear", "settled"], "cache is cleared before the re-layout notification");
  fake.emit("loadingdone");
  assert.deepEqual(events, ["clear", "settled", "clear", "settled"], "a later font load clears and re-lays out again");

  stop();
  assert.equal(fake.listenerCount("loadingdone"), 0, "cleanup removes the listener");
  fake.emit("loadingdone");
  assert.equal(events.length, 4, "no work after cleanup");
}

void main();
