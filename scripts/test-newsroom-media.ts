import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createDemoMediaBackend, createMediaBackend, type MediaDataClient } from "../lib/newsroom-media-backend";
import {
  imageDirective,
  insertDirectiveAtSelection,
  mediaIdFor,
  srcPathFor,
  uploadArticleImage,
  validateImageFile,
} from "../lib/newsroom-media";

type Case = { itemId: string; srcPath: string; expected: string };

async function main() {
  assert.equal(srcPathFor("my-post", "Diagram.PNG"), "assets/my-post/diagram.png");
  assert.equal(srcPathFor("my-post", "My Cool Photo (1).jpeg"), "assets/my-post/my-cool-photo-1.jpeg");
  assert.equal(srcPathFor("My Post!", "a.png"), "assets/my-post/a.png");
  assert.equal(srcPathFor("p", "...png"), "assets/p/image.png");
  assert.equal(srcPathFor("p", "a.png", ["assets/p/a.png"]), "assets/p/a-2.png");
  assert.equal(srcPathFor("p", "a.png", ["assets/p/a.png", "assets/p/a-2.png"]), "assets/p/a-3.png");

  assert.equal(validateImageFile({ name: "a.png", size: 100 }), null);
  for (const name of ["a.jpg", "a.JPEG", "a.gif", "a.webp", "a.avif", "a.svg"]) {
    assert.equal(validateImageFile({ name, size: 1 }), null, name);
  }
  assert.match(validateImageFile({ name: "a.pdf", size: 10 }) ?? "", /Choose a PNG/);
  assert.match(validateImageFile({ name: "noextension", size: 10 }) ?? "", /Choose a PNG/);
  assert.match(validateImageFile({ name: "a.png", size: 0 }) ?? "", /empty/);
  assert.equal(validateImageFile({ name: "a.png", size: 10 * 1024 * 1024 }), null);
  assert.match(validateImageFile({ name: "a.png", size: 10 * 1024 * 1024 + 1 }) ?? "", /10 MB/);

  const cases = JSON.parse(readFileSync("scripts/fixtures/media-id-cases.json", "utf8")) as Case[];
  assert.equal(cases.length, 5);
  for (const { itemId, srcPath, expected } of cases) {
    assert.equal(await mediaIdFor(itemId, srcPath), expected, srcPath);
  }

  assert.equal(
    imageDirective("assets/my-post/diagram.png", ""),
    '::image{src="assets/my-post/diagram.png" alt="" layout="inline"}',
  );
  const quoted = imageDirective("assets/p/a.png", 'He said "hi" {now}\nok');
  assert.equal(quoted, `::image{src="assets/p/a.png" alt="He said 'hi' now ok" layout="inline"}`);
  assert.equal((quoted.match(/"/g) ?? []).length, 6);

  const directive = imageDirective("assets/p/a.png", "");
  const empty = insertDirectiveAtSelection("", 0, 0, directive);
  assert.equal(empty.body, `${directive}\n`);
  assert.equal(empty.body.slice(empty.altSelectionStart - 5, empty.altSelectionStart + 1), 'alt=""');
  const middle = insertDirectiveAtSelection("Hello world", 5, 5, directive);
  assert.equal(middle.body, `Hello\n\n${directive}\n\n world`);
  const blankBefore = insertDirectiveAtSelection("One.\n\nTwo.", 6, 6, directive);
  assert.equal(blankBefore.body, `One.\n\n${directive}\n\nTwo.`);
  const replaced = insertDirectiveAtSelection("abc", 1, 2, directive);
  assert.equal(replaced.body, `a\n\n${directive}\n\nc`);
  assert.equal(blankBefore.body[blankBefore.altSelectionStart], '"');
  assert.equal(blankBefore.body[blankBefore.altSelectionStart - 1], '"');

  const created: unknown[] = [];
  const uploads: { path: string; contentType: string; size: number }[] = [];
  const existingRows = [
    {
      id: "m1",
      sortKey: "001#assets/harbor/pixel.png",
      storagePath: "media/assets/harbor/pixel.png",
      alt: "pixel.png",
      metadata: JSON.stringify({ srcPath: "assets/harbor/pixel.png" }),
    },
  ];
  const client: MediaDataClient = {
    models: {
      MediaAsset: {
        create: async (input, options) => {
          assert.equal(options.authMode, "userPool");
          created.push(input);
          return { errors: null };
        },
        listMediaAssetsByItemAndSortKey: async (input, options) => {
          assert.equal(input.itemId, "item-9");
          assert.equal(options.authMode, "userPool");
          return { data: existingRows, nextToken: null };
        },
      },
    },
  };
  const backend = createMediaBackend(() => client, {
    upload: async ({ path, contentType, data }) => {
      uploads.push({ path, contentType, size: data.size });
    },
    signedUrl: async (path) => `https://signed.example/${path}`,
  });
  const pngBytes = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const file = new File([pngBytes], "Pixel.PNG", { type: "image/png" });
  const uploaded = await uploadArticleImage(backend, async () => ({ width: 1, height: 1 }), {
    itemId: "item-9",
    slug: "harbor",
    file,
  });
  assert.equal(uploaded.srcPath, "assets/harbor/pixel-2.png");
  assert.equal(uploaded.directive, '::image{src="assets/harbor/pixel-2.png" alt="" layout="inline"}');
  assert.equal(uploaded.imageUrl, "https://signed.example/media/assets/harbor/pixel-2.png");
  assert.deepEqual(uploads, [{ path: "media/assets/harbor/pixel-2.png", contentType: "image/png", size: 8 }]);
  assert.equal(created.length, 1);
  const row = created[0] as Record<string, unknown>;
  assert.equal(row.id, await mediaIdFor("item-9", "assets/harbor/pixel-2.png"));
  assert.equal(row.itemId, "item-9");
  assert.equal(row.type, "image");
  assert.equal(row.role, "body");
  assert.equal(row.sortKey, "002#assets/harbor/pixel-2.png");
  assert.equal(row.storagePath, "media/assets/harbor/pixel-2.png");
  assert.equal(row.alt, "Pixel.PNG");
  assert.equal(row.width, 1);
  assert.equal(row.height, 1);
  const metadata = JSON.parse(row.metadata as string);
  assert.equal(metadata.srcPath, "assets/harbor/pixel-2.png");
  assert.equal(metadata.bytes, 8);
  assert.equal(metadata.contentType, "image/png");
  assert.match(metadata.sha256, /^[0-9a-f]{64}$/);

  const rejected = new File(["x"], "notes.txt");
  await assert.rejects(
    () => uploadArticleImage(backend, async () => null, { itemId: "item-9", slug: "harbor", file: rejected }),
    /Choose a PNG/,
  );
  assert.equal(created.length, 1);

  const failingBackend = createMediaBackend(() => client, {
    upload: async () => {
      throw new Error("Access Denied");
    },
    signedUrl: async () => "x",
  });
  await assert.rejects(
    () => uploadArticleImage(failingBackend, async () => null, { itemId: "item-9", slug: "harbor", file }),
    /Access Denied/,
  );
  assert.equal(created.length, 1);

  const demo = createDemoMediaBackend();
  await demo.uploadImage({ storagePath: "media/assets/x/a.png", data: new Blob(["a"]), contentType: "image/png" });
  assert.deepEqual(await demo.listMediaAssets("none"), []);

  console.log("newsroom media tests passed");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
