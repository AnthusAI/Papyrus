---
name: produce-video
description: Produce narrated article videos with `papyrus videos` (VideoML): script rules, narration, post-roll, render and attach.
---

# Produce Video (generic Papyrus pipeline)

Use this skill when generating or updating narrated MP4 videos for a publication's articles. Commands, config and content model: [docs/video-pipeline.md](../../docs/video-pipeline.md). A publication's own produce-video skill adds its voice, palette and pictogram rules and links here.

## Purpose

An article video is the article in video form: the same argument adapted for the ear, not a teaser. A viewer who presses play gets the substance. Write the scenes in tandem with the article body; when the body changes, revisit the scenes in the same change.

**No pre-roll.** The first scene is article content, given to the viewer first: never a welcome, never a masthead. All branding lives in the post-roll.

## Pipeline stages

1. Author `editorial.video.scenes` on the article `Item` (or let the fallback structure generate one).
2. `papyrus videos seed --dry-run` (or `render --probe-only`) to check the config, the scripts and the key without rendering.
3. `papyrus videos render --article <slug>` renders dark and light MP4s into the configured output directory.
4. Inspect a frame (not black, components visible) and measure the duration with `ffprobe`.
5. `papyrus videos attach --article <slug>`, then publish the item so the video reaches the reader.

## Scenes

```json
{ "kind": "quote", "quote": "...", "attribution": "...", "voice": "..." }
{ "kind": "slide", "eyebrow": "...", "title": "...", "subtitle": "...", "pictogram": "slug-or-omit", "voice": "..." }
```

- `voice` is required on every scene and is the narration. Display fields are short and poster-legible; they are not a transcript.
- Scene ids are generated (`scene-1`, `scene-2`, ...). Never author a closing or branding scene.
- Every scene needs visual content: slides need text or a pictogram. Voice-only scenes produce blank frames and are rejected.
- Slides render with the brand component named in `components.titleSlide`, quotes with `components.quoteCard`.

## Narration rules

1. Cold-open into content: scene 1 is usually the strongest pull quote, and it is the poster frame (two short sentences).
2. Cover the whole argument in roughly 350 to 450 spoken words: the claim, the example, the turn, the checks, the closing thought. Edit for the ear; do not read the body verbatim and do not drop substance.
3. A headline slide early is content, not branding. Its voice narrates the claim and never speaks the publication name as a welcome.
4. Displayed quotes occur verbatim in the article body.
5. Adjacent-scene echo rule: do not repeat distinctive phrasing in neighbouring scenes. Read the full voice script aloud, in order, before rendering.
6. Do not add claims the article does not make; do not invent facts.
7. Narration is public content: run the same vocabulary and policy checks as for article copy.

## Post-roll contract

The pipeline appends one standardized post-roll scene from the config `postRoll` block: end screen (eyebrow, title, tagline) and a spoken line from `postRoll.voice` with `{date}` replaced by the article's published date. It is never authored per video and the screen never varies. Only the spoken line may be overridden, with `editorial.video.postRollVoice`. The publication name is spoken only there.

## Credentials

The OpenAI key comes from `OPENAI_API_KEY` or `.papyrus/config.yaml`. Never commit keys or put them in the video config.
