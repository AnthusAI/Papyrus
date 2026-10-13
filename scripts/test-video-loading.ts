import assert from "node:assert/strict";
import { planVideoLoading, videoElementKey } from "../lib/video-loading";

assert.deepEqual(planVideoLoading({ hasHydrated: false, isNearViewport: true, hasPoster: true }), {
  attachSource: false,
  preload: "none",
});
assert.deepEqual(planVideoLoading({ hasHydrated: true, isNearViewport: false, hasPoster: false }), {
  attachSource: false,
  preload: "none",
});
assert.deepEqual(planVideoLoading({ hasHydrated: true, isNearViewport: true, hasPoster: true }), {
  attachSource: true,
  preload: "none",
});
assert.deepEqual(planVideoLoading({ hasHydrated: true, isNearViewport: true, hasPoster: false }), {
  attachSource: true,
  preload: "metadata",
});

assert.equal(videoElementKey(false, "/a.mp4"), videoElementKey(false, "/b.mp4"));
assert.notEqual(videoElementKey(true, "/a.mp4"), videoElementKey(true, "/b.mp4"));

console.log("video loading plan: ok");
