"""`papyrus stories capture-video-posters`: put our own copy of each ``::video`` thumbnail in the site's media storage.

A ``::video{...}`` is a click-to-play poster (``markus_renderer/video.py``). The poster must be ours: the page makes no request to YouTube or Google
before a click, so it cannot hot-link ``img.youtube.com``. The projector reads the poster like any stored picture, from
``media/assets/video-posters/<video id>.jpg`` and its renditions (the renditions function makes them when the object lands, the same one that
serves story pictures). Until the copy exists the page shows a flat placeholder with the video's title.

Fetching cannot happen inside the projection: YouTube refuses cloud addresses (the reason ``references capture-thumbnails`` is an operator command).
So a person signed in with ``papyrus login`` runs this where YouTube answers, once for each Story with a video, before publishing. It reads the
Story's current text, finds the ``::video`` directives, and for each video that has no copy yet fetches the thumbnail with the same code and checks
the Reference thumbnails use (``reference_thumbnails.fetch_thumbnail``: built from the video id, no API key, YouTube's grey stand-in refused) and
uploads it with the signed-in editor's identity-pool credentials. A video already stored is left alone; ``--dry-run`` lists what would be fetched.
"""
from __future__ import annotations

import re
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from .markus_renderer.content_markup import _VIDEO_DIRECTIVE_RE, parse_attrs
from .markus_renderer.video import VideoRequest, parse_video, provider_of
from .options import normalize_string, parse_options, resolve_mutation_apply
from .reference_thumbnails import NoThumbnail, Thumbnail, Unreachable, fetch_thumbnail, media_key_for_path

STOP_AFTER_UNREACHABLE = 3
EXIT_BLOCKED = 3
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")


def videos_in(body: str) -> tuple[list[VideoRequest], list[str]]:
    """The valid ``::video`` directives of a body, one for each distinct video, and a plain message for each directive that is not valid."""
    kept, lines, fence = [], [], None
    for line in body.split("\n"):
        marker = FENCE.match(line)
        if marker is not None:
            fence = None if fence == marker.group(1)[0] else (fence or marker.group(1)[0])
            kept.append("")
        else:
            kept.append("" if fence else line)
    found: dict[str, VideoRequest] = {}
    problems = []
    for match in _VIDEO_DIRECTIVE_RE.finditer("\n".join(kept)):
        attributes = parse_attrs(match.group("attrs"))
        if provider_of(attributes.get("src", "")) is None:
            continue   # not a YouTube address: a site's own embed, not core's
        try:
            request = parse_video(attributes, match.group(0))
        except ValueError as error:
            problems.append(str(error))
            continue
        found.setdefault(request.video_id, request)
    return list(found.values()), problems


def poster_media_key(request: VideoRequest) -> str:
    return media_key_for_path(request.poster_source)


def capture(request: VideoRequest, store: Any, *, fetch: Callable[[str], Thumbnail] = fetch_thumbnail, write: bool = True) -> tuple[str, str]:
    """``(outcome, detail)`` for one video: ``already_have``, ``would_fetch``, ``stored``, ``none`` (YouTube has no picture) or ``failed`` (try again later)."""
    key = poster_media_key(request)
    if store is not None and store.exists(key):
        return "already_have", request.poster_source
    if not write:
        return "would_fetch", request.poster_source
    try:
        thumbnail = fetch(request.watch_url)
    except NoThumbnail as reason:
        return "none", str(reason)
    except Unreachable as reason:
        return "failed", f"{str(reason)[:160]}; left for the next run"
    if thumbnail.extension != "jpg":
        return "none", f"YouTube gave a {thumbnail.media_type} picture, and the poster is a JPEG"
    with tempfile.TemporaryDirectory() as folder:
        local = Path(folder) / "poster.jpg"
        local.write_bytes(thumbnail.data)
        store.put(key, local, content_type=thumbnail.media_type, sha256=thumbnail.sha256)
    return "stored", f"{thumbnail.width}x{thumbnail.height}\t{request.poster_source}"


def stories_capture_video_posters(flags: list[str], *, client: Any = None, store: Any = None, out: TextIO | None = None,
                                  fetch: Callable[[str], Thumbnail] = fetch_thumbnail) -> int:
    """papyrus stories capture-video-posters --story <lineage> [--bucket NAME] [--identity-pool-id ID] [--dry-run]

    Copies the thumbnail of every YouTube video in the Story's current text into the site's media storage, where the page reads its poster from.
    Run it where YouTube answers (a home or office network, not a cloud machine), signed in as an editor or admin; no AWS credentials. Writes by
    default; --dry-run lists what it would fetch and contacts nobody. Exit status 3 when YouTube kept refusing this connection."""
    out = out or sys.stdout
    options = parse_options(flags)
    lineage = normalize_string(options.get("story"))
    if not lineage:
        raise ValueError("--story is required.")
    write = resolve_mutation_apply(options, "stories capture-video-posters")
    if client is None:
        from .graphql_authoring import create_authoring_client

        client, _ = create_authoring_client()
    from .story_reporting import current_story_version

    row = current_story_version(client, lineage)
    requests, problems = videos_in(str(row.get("bodyMarkus") or ""))
    for message in problems:
        print(f"stories\tcapture-video-posters\tinvalid\t{lineage}\t{message}", file=out)
    print(f"stories\tcapture-video-posters\tmode\t{'write' if write else 'dry run (nothing is fetched or written)'}\t{lineage}\t{len(requests)} video(s)", file=out)
    if store is None and requests:
        from .story_images import open_media_store

        store = open_media_store(normalize_string(options.get("bucket")), normalize_string(options.get("identity-pool-id")))
    counts: dict[str, int] = {}
    unreachable_in_a_row = 0
    for request in requests:
        outcome, detail = capture(request, store, fetch=fetch, write=write)
        counts[outcome] = counts.get(outcome, 0) + 1
        print("\t".join(["stories", "capture-video-posters", outcome, request.video_id, request.title[:80], detail]), file=out, flush=True)
        unreachable_in_a_row = unreachable_in_a_row + 1 if outcome == "failed" else 0
        if unreachable_in_a_row >= STOP_AFTER_UNREACHABLE:
            print("YouTube did not answer from this connection several times in a row. Run this where YouTube answers (a home or office network, not a cloud machine).", file=sys.stderr)
            return EXIT_BLOCKED
    summary = ", ".join(f"{name} {count}" for name, count in sorted(counts.items())) or "no videos"
    print(f"stories\tcapture-video-posters\tdone\t{summary}", file=out)
    if counts.get("stored"):
        print("stories\tcapture-video-posters\tnext\tthe renditions function makes the poster's sizes when the object lands; publish the Story after that", file=out)
    return 0
