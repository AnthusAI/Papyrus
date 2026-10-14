# Reader video loading

Tracked by PPY-79e668 (Threat Intelligence video loading).

## What was wrong

Measured on threat-intelligence.anth.us with headless Chrome, cache disabled, homepage `/` (307 to the current edition):

- The HTML is `cache-control: private, no-cache, no-store` on the redirect, so every visit pays the Next.js origin time (about 0.5 to 1.3 s TTFB, occasionally 6 s on a cold Amplify compute).
- Seven `<video preload="metadata">` elements render in the HTML, each with a `<source>` pointing at `/api/media/media/...mp4`. None has a poster.
- Every source is a 307 from the Next media route to a presigned S3 URL (`private, max-age=300`). There is no CDN in front of the media bucket.
- The MP4 files have the `moov` atom after `mdat` (not faststart), so for each element Chrome issues a plain GET, an open-ended Range request for the tail, and small Range requests.

Root causes of the repeated fetches (all in `components/article-video.tsx`):

1. The server render includes the `<source>`, so the browser starts fetching before hydration.
2. `key={hasHydrated ? src : "ssr"}` changes the key when hydration completes, so React unmounts the server element and mounts a new `<video>`, which fetches again.
3. The server render assumes the dark file and the client resolves the real theme afterwards, so a light-theme reader fetches the `-light.mp4` variant as well. Each of the two variants is a different URL, and each 307 target is a different presigned URL, so nothing is shared in the browser cache.
4. `preload="metadata"` on every element, whether or not the reader ever scrolls to it.

## The component fix

`lib/video-loading.ts` decides, from `hasHydrated`, `isNearViewport` and `hasPoster`, whether the `<source>` is attached and what `preload` is. `components/use-near-viewport.ts` observes the figure with an IntersectionObserver (200px margin) and flips once. The server render attaches no source. A video with a poster preloads nothing until the reader presses play. A video without a poster preloads metadata only once it is near the viewport. The element key no longer changes at hydration.

## Measurements

Same Chrome, same method (`Network` domain events, cache disabled, 8 s settle). Harness: the old and new `ArticleVideoFigure` rendered with `renderToString` and hydrated, seven real TI videos with their light variants as theme variants, 900 px apart, light theme. Both pages also ship the same unminified client bundle.

| | Before (production, real site) | Before (harness, old component) | After (harness, new component) |
| --- | --- | --- | --- |
| Requests on load | 97 | 47 | 9 |
| Video requests on load | 52 | 44 | 6 |
| Video bytes on load | 6.5 MB | 5.8 MB | 2.1 MB |
| Distinct video files requested | 12 | 12 | 2 |
| Requests per fetched video file | 3 to 8 | 3 to 7 | 3 |

The 310 MB figure reported earlier was not reproduced as bytes on the wire (this run transferred 9.4 MB in 97 requests). Chrome cancels the plain GET after metadata, so the large number is most likely declared lengths or a slower connection that lets the body continue. The structure (about 50 video requests, every video requested in both themes, each three or more times) is reproduced.

Faststart effect, one article video, Chrome, `preload="metadata"`: 4 requests before the remux, 2 after.

## Media encodes

Current files in the TI media bucket: 14 MP4 files, 153 MB in total. Overview 26.6 MB (443 s), articles 8.1 to 9.9 MB (about 215 s). Every file: H.264 High 1280x720 30 fps at 175 to 290 kbps, AAC-LC mono at 180 kbps, `moov` after `mdat`, `Cache-Control: public, max-age=31536000, immutable` (already set). The audio is more than half of the bits.

Plan, applied by `scripts/video/prepare-web-video.sh` to a local copy (it never touches S3):

- Video stream copied unchanged. Audio re-encoded to AAC 96 kbps (mono). `-movflags +faststart` moves `moov` to the front.
- Poster: frame at 1 s scaled to 1280 px wide, WebP quality 70 (12 KB for the sample) next to each video as `<name>.poster.webp`. Set the asset's `metadata.posterSrc` to the poster path.
- Size estimate: sample article video 9.77 MB to 7.60 MB (minus 22 percent). Whole bucket 153 MB to about 119 MB with 96 kbps audio, about 105 MB with 64 kbps mono. Faststart alone changes nothing in size.
- Upload (a separate, approved step): upload new keys with `Cache-Control: public, max-age=31536000, immutable`, then switch the asset records. Do not overwrite the existing keys in place, because immutable copies are cached for a year.

## CloudFront for the media bucket

Today the bucket is private (anonymous GET returns 403, Block Public Access on). The reader gets bytes through the Next route `/api/media/*`, which signs a URL with the Cognito guest role (guest read on `media/*`) and redirects. The access semantics to keep: only objects under `media/` are readable, and only through the site.

Proposed (`infra/edge/threat-intelligence-media.yaml`, not deployed): the existing `papyrus-edge-threat-intelligence` stack gets, on both distributions, a second origin (the media bucket) with a new origin access control, and a cache behavior for `/api/media/media/*` using the managed CachingOptimized policy. A viewer-request function maps `/api/media/media/<key>` to `/media/<key>`, so no URL in the content changes and the Next route stays as the fallback for other paths. The objects already carry an immutable year-long Cache-Control. The default behavior (Amplify) is untouched.

One more change is needed outside that stack. The bucket policy belongs to the Amplify storage stack (a bucket has one policy), so the Papyrus backend must add this statement to the media bucket policy, and it ships with a pin bump and a backend deploy:

```json
{
  "Effect": "Allow",
  "Principal": { "Service": "cloudfront.amazonaws.com" },
  "Action": "s3:GetObject",
  "Resource": "arn:aws:s3:::<media-bucket>/media/*",
  "Condition": { "StringEquals": { "AWS:SourceArn": [
    "arn:aws:cloudfront::712236451410:distribution/E20NJAIXZ1WKWD",
    "arn:aws:cloudfront::712236451410:distribution/E5LPOQYKD91KN"
  ] } }
}
```

Note that `media/` includes `media/payloads/...` (article bodies and excerpts). They are already guest-readable. Narrowing the behavior to `/api/media/media/articles/*` and `/api/media/media/editions/*` would keep payloads off the CDN.

Order of operations: bucket policy statement first, then the edge change set. Create the change set, read it, and execute only with approval:

```
aws cloudformation create-change-set --stack-name papyrus-edge-threat-intelligence --change-set-name media-behavior --template-body file://infra/edge/threat-intelligence-media.yaml --parameters ParameterKey=CertificateArn,UsePreviousValue=true --region us-east-1
```
