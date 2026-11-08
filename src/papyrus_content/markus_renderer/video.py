"""``::video{...}``: a playable video in a Story, written like ``::image{...}`` (docs/markus-content-markup.md, "Videos").

A video is a click-to-play poster, never an always-loaded frame. The page holds our own copy of the video's thumbnail (the poster) and a
real ``<button>``; only a click swaps in the provider's privacy-enhanced player (``papyrus-video-v1.js``). Nothing in the static HTML makes a
request to the provider: the poster is in the site's own storage and the only provider addresses on the page are the plain link and the
player address kept in a ``data-`` attribute for the script.

This module is the pure part: reading the attributes (``parse_video``), the provider rule (YouTube only, through the one parser the Reference
code already uses), and the HTML (``render_video``). Nothing here reads the site's storage or settings; the projector hands in the poster
markup it found (or ``None``) and the site's ``VideoRendering``.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass

from ..youtube_transcript import YOUTUBE_HOSTS, video_id as youtube_video_id

#: The providers a ``::video`` may name. The setting ``embeds.providers`` chooses among these for a site.
PROVIDERS = ("youtube",)
PROVIDER_WORDS = "YouTube (youtube.com, youtu.be, youtube-nocookie.com)"
ALLOWED_ATTRIBUTES = ("src", "title", "caption", "credit", "start", "layout")
LAYOUTS = ("inline", "full")
DEFAULT_LAYOUT = "inline"
ADDRESS_SHAPES = "https://www.youtube.com/watch?v=ID, https://youtu.be/ID, https://www.youtube.com/shorts/ID, https://www.youtube.com/live/ID or https://www.youtube.com/embed/ID"

#: The poster is our own copy of the video's thumbnail, in the site's media storage; this is where ``papyrus stories capture-video-posters`` puts it.
POSTER_DIRECTORY = "assets/video-posters"
#: The only frame address the player script may create; the markup keeps it in ``data-embed`` and the script refuses any other.
EMBED_ORIGIN = "https://www.youtube-nocookie.com"
EMBED_PATH = "/embed/"
#: The origins a page may frame for each provider: what ``embeds`` turns into the site's ``frame-src`` rule.
FRAME_ORIGINS = {"youtube": EMBED_ORIGIN}

SCRIPT_PATH = "_plugins/papyrus-video-v1.js"

#: Lucide ``play`` (lucide.dev, ISC licence), drawn as a flat filled shape in the button's own colour.
PLAY_ICON = (
    '<svg class="papyrus-video-icon" xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="currentColor" '
    'stroke="none" aria-hidden="true" focusable="false" data-icon="play"><path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"/></svg>'
)

#: Stock rules, emitted once per page by the first video. Colours come from the site's own tokens with a flat fallback; no outlines, no hairlines.
#: The ratio is the design system's media ratio token. Without the script the button stays hidden and the poster is a link.
STYLE = (
    ".papyrus-video-player{position:relative;overflow:hidden;aspect-ratio:var(--papyrus-media-ratio,16 / 9);"
    "border-radius:var(--papyrus-radius,.5rem);background:var(--papyrus-media-bg,color-mix(in srgb,currentColor 12%,transparent))}"
    ".papyrus-video-link{position:absolute;inset:0;display:block;color:inherit;text-decoration:none}"
    ".papyrus-video-poster,.papyrus-video-poster picture{display:block;width:100%;height:100%}"
    ".papyrus-video-poster img{display:block;width:100%;height:100%;object-fit:cover}"
    ".papyrus-video-title{position:absolute;left:0;right:0;bottom:0;padding:.75rem 1rem;font-weight:600;"
    "background:var(--papyrus-media-scrim,rgba(0,0,0,.72));color:var(--papyrus-media-scrim-ink,#fff)}"
    ".papyrus-video-play{display:none;position:absolute;inset:0;width:100%;height:100%;margin:0;padding:0;border:0;border-radius:inherit;"
    "background:transparent;color:var(--papyrus-media-play-ink,#fff);cursor:pointer;align-items:center;justify-content:center}"
    ".papyrus-video-play::before{content:\"\";position:absolute;width:4.5rem;height:4.5rem;border-radius:50%;"
    "background:var(--papyrus-media-play-bg,rgba(0,0,0,.72))}"
    ".papyrus-video-play .papyrus-video-icon{position:relative;width:1.75rem;height:1.75rem;margin-left:.2rem}"
    ".papyrus-video-play:hover::before,.papyrus-video-play:focus-visible::before{background:var(--papyrus-media-play-hover,rgba(0,0,0,.88))}"
    ".papyrus-video-play:focus-visible{outline:3px solid var(--papyrus-focus,currentColor);outline-offset:-3px}"
    ".papyrus-video-player.is-ready .papyrus-video-play{display:flex}"
    ".papyrus-video-player.is-ready .papyrus-video-link{display:none}"
    ".papyrus-video-player iframe{position:absolute;inset:0;width:100%;height:100%;border:0}"
    ".papyrus-video-placeholder{display:block;width:100%;height:100%}"
    "@media (prefers-color-scheme:dark){.papyrus-video-player{background:var(--papyrus-media-bg,color-mix(in srgb,currentColor 18%,transparent))}}"
)


@dataclass(frozen=True)
class VideoRequest:
    """One ``::video{...}`` as written."""

    src: str
    video_id: str
    title: str
    credit: str
    caption: str | None = None
    start: int | None = None
    layout: str = DEFAULT_LAYOUT
    provider: str = "youtube"

    @property
    def watch_url(self) -> str:
        """The plain address of the video on the provider (every address shape written the same way), with the start time when there is one."""
        suffix = f"&t={self.start}s" if self.start else ""
        return f"https://www.youtube.com/watch?v={self.video_id}{suffix}"

    @property
    def poster_source(self) -> str:
        """The site storage path of the poster: ``assets/video-posters/<id>.jpg``."""
        return poster_source(self.video_id)

    @property
    def embed_url(self) -> str:
        """The privacy-enhanced player address the script creates on a click."""
        query = {"autoplay": "1", **({"start": str(self.start)} if self.start else {}), "rel": "0"}
        return f"{EMBED_ORIGIN}{EMBED_PATH}{self.video_id}?{urllib.parse.urlencode(query)}"


@dataclass(frozen=True)
class VideoRendering:
    """What a site lets a video be (``projection.json`` ``embeds``). Off (the default): core does not read ``::video`` at all, so it reaches any site hook as before."""

    enabled: bool = False
    providers: tuple[str, ...] = PROVIDERS

    @property
    def frame_origins(self) -> tuple[str, ...]:
        return tuple(FRAME_ORIGINS[name] for name in self.providers if name in FRAME_ORIGINS)


def poster_source(identifier: str) -> str:
    return f"{POSTER_DIRECTORY}/{identifier}.jpg"


def provider_of(address: str) -> str | None:
    """The supported provider an address belongs to (by its host), or ``None``. Core handles only these; any other ``::video`` address is a site's own business."""
    try:
        parts = urllib.parse.urlsplit((address or "").strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    return "youtube" if parts.scheme in ("http", "https") and host in {*YOUTUBE_HOSTS, "youtu.be"} else None


def video_id_of(address: str) -> str:
    """The video id of a YouTube address, with the plain-words error naming the allowed providers for anything else.

    Uses the parser the Reference code reads video addresses with (``youtube_transcript.video_id``); this adds only the explanation and the check that
    the address is a web address."""
    value = (address or "").strip()
    try:
        parts = urllib.parse.urlsplit(value)
        host = (parts.hostname or "").lower()
    except ValueError:
        parts, host = None, ""
    if parts is None or parts.scheme not in ("http", "https") or host not in {*YOUTUBE_HOSTS, "youtu.be"}:
        raise ValueError(f"src {value!r} is not an address of a supported video provider. Allowed providers: {PROVIDER_WORDS}.")
    found = youtube_video_id(value)
    if found is None:
        raise ValueError(f"src {value!r} is a YouTube address without a video in it. Use {ADDRESS_SHAPES}.")
    return found


def parse_video(attributes: dict[str, str], written: str = "") -> VideoRequest:
    """Check the attributes of a ``::video{...}`` whose address is a supported provider's; ``ValueError`` names what to change."""
    where = "::video{...}"
    unknown = set(attributes) - set(ALLOWED_ATTRIBUTES)
    if unknown:
        raise ValueError(f"{where} got unknown attribute(s) {', '.join(sorted(unknown))}. Allowed: {', '.join(ALLOWED_ATTRIBUTES)}.")
    src = (attributes.get("src") or "").strip()
    if not src:
        raise ValueError(f"{where} needs a src attribute: the address of a YouTube video ({ADDRESS_SHAPES}): {written.strip()!r}")
    try:
        identifier = video_id_of(src)
    except ValueError as error:
        raise ValueError(f"{where} {error}") from None
    title = " ".join((attributes.get("title") or "").split())
    if not title:
        raise ValueError(f'{where} needs a title attribute: the accessible name of the player, for example title="Aircraft sound localisation demonstration".')
    credit = " ".join((attributes.get("credit") or "").split())
    if not credit:
        raise ValueError(f'{where} needs a credit attribute: the channel or person who made the video, for example credit="Example Channel". Third-party media is always credited.')
    start = None
    if attributes.get("start") not in (None, ""):
        raw = attributes["start"].strip()
        if not re.fullmatch(r"\d{1,6}", raw):
            raise ValueError(f'{where} start must be whole seconds such as start="90", not {raw!r}.')
        start = int(raw)
    layout = (attributes.get("layout") or DEFAULT_LAYOUT).strip()
    if layout not in LAYOUTS:
        raise ValueError(f'{where} layout must be one of {", ".join(LAYOUTS)}, not {layout!r}.')
    caption = " ".join((attributes.get("caption") or "").split()) or None
    return VideoRequest(src=src, video_id=identifier, title=title, credit=credit, caption=caption, start=start, layout=layout)


def _q(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_video(
    request: VideoRequest,
    rendering: VideoRendering,
    *,
    poster: str | None = None,
    classes: str = "",
    with_style: bool = True,
) -> str:
    """The figure for one video (only called for a site whose ``embeds`` are on: with embeds off core does not read ``::video`` at all).

    ``poster`` is the finished markup of our own copy of the thumbnail (a ``<picture>`` or ``<img>``), or ``None`` when the copy is missing, which
    shows a flat placeholder with the title: never a broken image and never an address on the provider. ``classes`` are the figure's classes (the
    image layout classes plus ``papyrus-video``).
    """
    watch = _q(request.watch_url)
    caption_bits = []
    if request.caption:
        caption_bits.append(_q(request.caption))
    caption_bits.append(f'<span class="papyrus-image-credit"><a href="{watch}" rel="noopener noreferrer">{_q(request.credit)}</a></span>')
    caption = f'<figcaption>{" · ".join(caption_bits)}</figcaption>'
    figure_classes = _q(" ".join(part for part in (classes, "papyrus-video") if part))
    surface = poster if poster else '<span class="papyrus-video-placeholder" aria-hidden="true"></span>'
    style = f"<style>{STYLE}</style>" if with_style else ""
    return (
        f"{style}<figure class=\"{figure_classes}\">"
        f'<div class="papyrus-video-player" data-papyrus-video="" data-provider="{_q(request.provider)}" data-embed="{_q(request.embed_url)}" '
        f'data-title="{_q(request.title)}">'
        f'<a class="papyrus-video-link" href="{watch}" rel="noopener noreferrer">'
        f'<span class="papyrus-video-poster">{surface}</span><span class="papyrus-video-title">{_q(request.title)}</span></a>'
        f'<button type="button" class="papyrus-video-play" aria-label="{_q(request.title)}">{PLAY_ICON}</button>'
        f"</div>{caption}</figure>"
    )


def csp_directives(rendering: VideoRendering) -> dict[str, tuple[str, ...]]:
    """The Content-Security-Policy directives a site with these ``embeds`` needs, and nothing more: ``frame-src`` for the player's origin. None when embeds are off."""
    if not rendering.enabled or not rendering.frame_origins:
        return {}
    return {"frame-src": rendering.frame_origins}


def csp_text(rendering: VideoRendering) -> str:
    """The same as one policy fragment: ``frame-src https://www.youtube-nocookie.com`` (empty when embeds are off)."""
    return "; ".join(f"{name} {' '.join(sources)}" for name, sources in csp_directives(rendering).items())
