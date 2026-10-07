import assert from "node:assert/strict";
import { buildMediaRouteResponse, isProxiedImagePath } from "../lib/media-route-response";

const fakeSignedUrl = "https://example-bucket.s3.amazonaws.com/media/x?signature=fake";

function createDependencies(upstream: Response) {
  const calls = { signed: [] as string[], fetched: [] as string[] };
  return {
    calls,
    dependencies: {
      signStorageUrl: async (storagePath: string) => {
        calls.signed.push(storagePath);
        return fakeSignedUrl;
      },
      fetchUpstream: async (signedUrl: string) => {
        calls.fetched.push(signedUrl);
        return upstream;
      },
    },
  };
}

async function main() {
  assert.equal(isProxiedImagePath("media/a/b.JPG"), true);
  assert.equal(isProxiedImagePath("media/a/b.mp4"), false);
  assert.equal(isProxiedImagePath("media/a/noextension"), false);

  const video = createDependencies(new Response("never read"));
  const videoResponse = await buildMediaRouteResponse("media/a/b.mp4", video.dependencies);
  assert.equal(videoResponse.status, 307);
  assert.equal(videoResponse.headers.get("location"), fakeSignedUrl);
  assert.deepEqual(video.calls.fetched, []);

  const image = createDependencies(new Response("bytes", { headers: { "content-type": "image/png" } }));
  const imageResponse = await buildMediaRouteResponse("media/a/b.png", image.dependencies);
  assert.equal(imageResponse.status, 200);
  assert.equal(imageResponse.headers.get("content-type"), "image/png");
  assert.equal(await imageResponse.text(), "bytes");

  const missing = createDependencies(new Response("", { status: 404 }));
  assert.equal((await buildMediaRouteResponse("media/a/b.png", missing.dependencies)).status, 404);
  const broken = createDependencies(new Response("", { status: 500 }));
  assert.equal((await buildMediaRouteResponse("media/a/b.png", broken.dependencies)).status, 502);
  console.log("media route response tests passed");
}

main();
