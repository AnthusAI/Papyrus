"""``::video{...}``: a playable video in a Story, written like ``::image{...}`` (docs/markus-content-markup.md, "Videos").

A video is the provider's standard embed: an ``<iframe>`` in which the provider draws its own thumbnail and play button. There is no poster of ours,
no placeholder and no script of ours; the provider loads with the page (YouTube through ``youtube-nocookie.com``, Vimeo with ``dnt=1``).

Providers are data. ``REGISTRY`` below is the one list of the providers Papyrus knows: how to recognise an address, how to name the video, the
plain address, the iframe address and the origins the site's Content-Security-Policy must allow. A site chooses which providers play with
``embeds.providers`` (empty by default: the feature is then not there at all).

This module is the pure part: reading the attributes (``parse_video``), the registry, and the HTML (``render_video`` / ``render_plain``).
"""

from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass
from types import MappingProxyType

from ..youtube_transcript import YOUTUBE_HOSTS, video_id as youtube_video_id


@dataclass(frozen=True)
class Provider:
    """One video provider, as data."""

    name: str
    label: str
    hosts: frozenset[str]
    #: ``(path regex, id group)`` pairs tried against the address path; YouTube also has its own parser (its ids live in a query too).
    path_patterns: tuple[str, ...]
    #: The plain address of a video (``{id}``), and how a start time is written onto it.
    watch: str
    watch_start: str
    #: The iframe address (``{id}``), its fixed query, and how a start time is written onto it.
    embed: str
    embed_query: tuple[tuple[str, str], ...]
    embed_start: str
    #: Every origin the iframe may load from (the site's ``frame-src``).
    frame_origins: tuple[str, ...] = ()
    #: ``aspect-ratio`` of the frame wrapper (a portrait post is not 16 / 9) and the least height it may have.
    ratio: str = "16 / 9"
    min_height: str | None = None
    address_shapes: str = ""

    @property
    def start_supported(self) -> bool:
        return bool(self.watch_start or self.embed_start)


#: Everything Papyrus knows about video providers. Adding a provider is adding a row here.
REGISTRY: "MappingProxyType[str, Provider]" = MappingProxyType({
    "youtube": Provider(
        name="youtube", label="YouTube", hosts=frozenset({*YOUTUBE_HOSTS, "youtu.be"}), path_patterns=(),
        watch="https://www.youtube.com/watch?v={id}", watch_start="&t={start}s",
        embed="https://www.youtube-nocookie.com/embed/{id}", embed_query=(), embed_start="query:start",
        frame_origins=("https://www.youtube-nocookie.com", "https://www.youtube.com"),
        address_shapes="https://www.youtube.com/watch?v=ID, https://youtu.be/ID, https://www.youtube.com/shorts/ID, https://www.youtube.com/live/ID or https://www.youtube.com/embed/ID",
    ),
    "vimeo": Provider(
        name="vimeo", label="Vimeo", hosts=frozenset({"vimeo.com", "www.vimeo.com", "player.vimeo.com"}),
        path_patterns=(r"^/(?:video/|channels/[\w-]+/|groups/[\w-]+/videos/|album/\d+/video/)?(?P<id>\d{4,12})/?$",),
        watch="https://vimeo.com/{id}", watch_start="#t={start}s",
        embed="https://player.vimeo.com/video/{id}", embed_query=(("dnt", "1"),), embed_start="fragment:t={start}s",
        frame_origins=("https://player.vimeo.com",),
        address_shapes="https://vimeo.com/ID or https://player.vimeo.com/video/ID",
    ),
    "instagram": Provider(
        name="instagram", label="Instagram", hosts=frozenset({"instagram.com", "www.instagram.com"}),
        path_patterns=(r"^/(?:[\w.]+/)?(?:p|reel|reels|tv)/(?P<id>[\w-]{5,30})/?$",),
        watch="https://www.instagram.com/p/{id}/", watch_start="",
        embed="https://www.instagram.com/p/{id}/embed/", embed_query=(), embed_start="",
        frame_origins=("https://www.instagram.com",), ratio="4 / 5", min_height="30rem",
        address_shapes="https://www.instagram.com/p/ID/, https://www.instagram.com/reel/ID/ or https://www.instagram.com/tv/ID/",
    ),
})
#: The provider names, in the order the registry lists them: what ``embeds.providers`` may name.
PROVIDERS = tuple(REGISTRY)
PROVIDER_WORDS = ", ".join(provider.label for provider in REGISTRY.values())
ALLOWED_ATTRIBUTES = ("src", "title", "caption", "credit", "start", "layout", "poster")  # ``poster`` is accepted and ignored: older lines keep working
LAYOUTS = ("inline", "full")
DEFAULT_LAYOUT = "inline"

#: Stock rules, emitted once per page by the first video: the wrapper keeps the provider's ratio and the frame fills it.
STYLE = (
    ".papyrus-video-frame{position:relative;width:100%;aspect-ratio:16 / 9;overflow:hidden;border-radius:var(--papyrus-radius,.5rem)}"
    ".papyrus-video-frame iframe{position:absolute;inset:0;display:block;width:100%;height:100%;border:0;border-radius:inherit}"
)
#: A provider whose frame is not 16 / 9 (a portrait post) says so in the registry; its rule is added here so the registry stays the one list.
STYLE += "".join(
    f'.papyrus-video-frame[data-provider="{spec.name}"]{{aspect-ratio:{spec.ratio}'
    + (f";min-height:{spec.min_height};max-width:34rem;margin-inline:auto" if spec.min_height else "") + "}"
    for spec in REGISTRY.values() if spec.ratio != "16 / 9"
)
IFRAME_ALLOW = "accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"


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
    def spec(self) -> Provider:
        return REGISTRY[self.provider]

    @property
    def watch_url(self) -> str:
        """The plain address of the video on the provider (every address shape written the same way), with the start time when there is one."""
        spec = self.spec
        suffix = spec.watch_start.format(start=self.start) if self.start and spec.watch_start else ""
        return spec.watch.format(id=self.video_id) + suffix

    @property
    def embed_url(self) -> str:
        """The iframe address, with the start time when there is one."""
        spec = self.spec
        query = dict(spec.embed_query)
        address = spec.embed.format(id=self.video_id)
        fragment = ""
        if self.start and spec.embed_start.startswith("query:"):
            query[spec.embed_start.split(":", 1)[1]] = str(self.start)
        if self.start and spec.embed_start.startswith("fragment:"):
            fragment = "#" + spec.embed_start.split(":", 1)[1].format(start=self.start)
        return address + (f"?{urllib.parse.urlencode(query)}" if query else "") + fragment


@dataclass(frozen=True)
class VideoRendering:
    """What a site lets a video be (``projection.json`` ``embeds``): the providers that play. Empty (the default): core does not read ``::video`` at all, so it reaches any site hook as before."""

    providers: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return bool(self.providers)

    @property
    def frame_origins(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(origin for name in self.providers if name in REGISTRY for origin in REGISTRY[name].frame_origins))


def provider_of(address: str) -> str | None:
    """The registered provider an address belongs to (by its host), or ``None``. Any other ``::video`` address is a site's own business."""
    try:
        parts = urllib.parse.urlsplit((address or "").strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    return next((name for name, spec in REGISTRY.items() if host in spec.hosts), None)


def _id_in(spec: Provider, value: str) -> str | None:
    if spec.name == "youtube":
        return youtube_video_id(value)
    path = urllib.parse.urlsplit(value).path
    for pattern in spec.path_patterns:
        found = re.match(pattern, path)
        if found:
            return found.group("id")
    return None


def parse_address(address: str) -> tuple[str, str]:
    """``(provider, video id)`` of an address, with the plain-words error naming the allowed providers for anything else."""
    value = (address or "").strip()
    name = provider_of(value)
    if name is None:
        raise ValueError(f"src {value!r} is not an address of a supported video provider. Allowed providers: {PROVIDER_WORDS}.")
    spec = REGISTRY[name]
    found = _id_in(spec, value)
    if found is None:
        raise ValueError(f"src {value!r} is a {spec.label} address without a video in it. Use {spec.address_shapes}.")
    return name, found


def video_id_of(address: str) -> str:
    """The video id of a supported address (``ValueError`` as ``parse_address``)."""
    return parse_address(address)[1]


def parse_video(attributes: dict[str, str], written: str = "") -> VideoRequest:
    """Check the attributes of a ``::video{...}`` whose address is a registered provider's; ``ValueError`` names what to change."""
    where = "::video{...}"
    unknown = set(attributes) - set(ALLOWED_ATTRIBUTES)
    if unknown:
        raise ValueError(f"{where} got unknown attribute(s) {', '.join(sorted(unknown))}. Allowed: {', '.join(ALLOWED_ATTRIBUTES)}.")
    src = (attributes.get("src") or "").strip()
    if not src:
        raise ValueError(f"{where} needs a src attribute: the address of a video ({PROVIDER_WORDS}): {written.strip()!r}")
    try:
        provider, identifier = parse_address(src)
    except ValueError as error:
        raise ValueError(f"{where} {error}") from None
    spec = REGISTRY[provider]
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
        if not spec.start_supported:
            raise ValueError(f"{where} start is not supported for {spec.label} videos.")
        start = int(raw)
    layout = (attributes.get("layout") or DEFAULT_LAYOUT).strip()
    if layout not in LAYOUTS:
        raise ValueError(f'{where} layout must be one of {", ".join(LAYOUTS)}, not {layout!r}.')
    caption = " ".join((attributes.get("caption") or "").split()) or None
    return VideoRequest(src=src, video_id=identifier, title=title, credit=credit, caption=caption, start=start, layout=layout, provider=provider)


def _q(value: object) -> str:
    return html.escape(str(value), quote=True)


def _caption(request: VideoRequest) -> str:
    watch = _q(request.watch_url)
    bits = [_q(request.caption)] if request.caption else []
    bits.append(f'<span class="papyrus-image-credit"><a href="{watch}" rel="noopener noreferrer">{_q(request.credit)}</a></span>')
    return f'<figcaption>{" · ".join(bits)}</figcaption>'


def render_plain(request: VideoRequest) -> str:
    """The plain linked credit line a site with embeds on shows for a video whose provider it has not listed: no player, no picture, no script.

    ``Video: <title linked to the video>. <caption>. Credit: <credit>.``"""
    watch = _q(request.watch_url)
    bits = [f'Video: <a href="{watch}" rel="noopener noreferrer">{_q(request.title)}</a>.']
    if request.caption:
        bits.append(f"{_q(request.caption)}")
    bits.append(f"Credit: {_q(request.credit)}.")
    return f'<p class="papyrus-video-line">{" ".join(bits)}</p>'


def render_video(
    request: VideoRequest,
    rendering: VideoRendering,
    *,
    classes: str = "",
    with_style: bool = True,
) -> str:
    """The figure for one video (only called for a provider the site lists in ``embeds.providers``): the provider's own iframe in a ratio wrapper,
    then the caption and the linked credit. ``classes`` are the figure's classes (the image layout classes plus ``papyrus-video``)."""
    figure_classes = _q(" ".join(part for part in (classes, "papyrus-video") if part))
    style = f"<style>{STYLE}</style>" if with_style else ""
    return (
        f"{style}<figure class=\"{figure_classes}\">"
        f'<div class="papyrus-video-frame" data-provider="{_q(request.provider)}">'
        f'<iframe src="{_q(request.embed_url)}" title="{_q(request.title)}" loading="lazy" allowfullscreen '
        f'referrerpolicy="strict-origin-when-cross-origin" allow="{IFRAME_ALLOW}"></iframe>'
        f"</div>{_caption(request)}</figure>"
    )


def csp_directives(rendering: VideoRendering) -> dict[str, tuple[str, ...]]:
    """The Content-Security-Policy directives a site with these ``embeds`` needs, and nothing more: ``frame-src`` for the player's origin. None when embeds are off."""
    if not rendering.enabled or not rendering.frame_origins:
        return {}
    return {"frame-src": rendering.frame_origins}


def csp_text(rendering: VideoRendering) -> str:
    """The same as one policy fragment: ``frame-src https://www.youtube-nocookie.com`` (empty when embeds are off)."""
    return "; ".join(f"{name} {' '.join(sources)}" for name, sources in csp_directives(rendering).items())
