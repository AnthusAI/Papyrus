"""`papyrus stories save-version --images <dir>`: upload the local pictures a story body uses.

Plans exactly what the newsroom editor's "Insert image" stores (``lib/newsroom-media.ts``: ``srcPathFor``,
``mediaIdFor``, the ``MediaAsset`` fields and the ``media/<srcPath>`` S3 key) and what the Markus import stores,
then rewrites the body's ``src`` (and ``srcDark``) to the stored paths. Planning is pure: it reads local files,
validates every one of them, and touches neither S3 nor the backend, so ``--dry-run`` and every rejection happen
before any write.

Which lanes can upload (see the stories docs): the IAM lane writes to S3 with the caller's AWS credentials; the
signed-in user lane (``PAPYRUS_GRAPHQL_AUTH=user``) trades its Cognito ID token for temporary credentials from the
site's identity pool, exactly as the browser editor's storage client does, so the ``editor``/``admin`` group's
``media/*`` write rule applies. ``createModelAttachmentUpload`` cannot be used: it only issues keys under
``newsroom/payloads`` and ``media/payloads``, never ``media/assets``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .markus_import import IMAGE_CONTENT_TYPES, media_id_for, tenant_stored_media_path
from .markus_renderer.content_markup import _ATTR_RE, _IMAGE_DIRECTIVE_RE
from .record_helpers import to_aws_json

#: The editor's limit (``MAX_IMAGE_BYTES``).
MAX_IMAGE_BYTES = 10 * 1024 * 1024
#: Light and dark files may differ in aspect ratio by at most this fraction (the renderer's own tolerance).
DARK_ASPECT_TOLERANCE = 0.005
ALLOWED_TYPES_TEXT = "PNG, JPEG, GIF, WebP, AVIF or SVG"

_MARKDOWN_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]\n]*)\]\((?P<src>[^)\s]+)(?P<title>\s+\"[^\"]*\")?\)")
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})", re.M)
_SVG_SIZE_RE = re.compile(r"<svg\b[^>]*>", re.I | re.S)


def sanitize_segment(value: str) -> str:
    value = re.sub(r"[^a-z0-9._-]+", "-", value.lower())
    value = re.sub(r"-{2,}", "-", value)
    return re.sub(r"^[-.]+|-+$", "", value)


def src_path_for(slug: str, filename: str, taken: set[str] | None = None) -> str:
    """Port of ``srcPathFor``: ``assets/<slug>/<stem>.<ext>``, numbered ``-2``, ``-3`` when taken."""
    taken = taken if taken is not None else set()
    dot = filename.rfind(".")
    extension = sanitize_segment(filename[dot + 1:].lower()) if dot != -1 else ""
    raw_stem = filename[:dot] if dot != -1 else filename
    stem = sanitize_segment(raw_stem) or "image"
    directory = sanitize_segment(slug) or "article"
    suffix = f".{extension}" if extension else ""
    candidate = f"assets/{directory}/{stem}{suffix}"
    counter = 2
    while candidate in taken:
        candidate = f"assets/{directory}/{stem}-{counter}{suffix}"
        counter += 1
    return candidate


@dataclass
class PlannedStoryImage:
    ref: str  # the reference as written in the body
    local_path: Path
    role: str  # "light" or "dark"
    src_path: str  # what the body points at afterwards (``assets/<slug>/<file>``)
    storage_path: str  # the S3 key
    content_type: str
    size: int
    sha256: str
    width: int | None
    height: int | None
    paired_with: str | None = None  # for a dark file: the light file's ref
    position: int = 0
    ratio: float | None = None  # width / height, for the light/dark check (also known for SVG)

    @property
    def filename(self) -> str:
        return self.local_path.name

    def media_row(self, item_id: str) -> dict[str, Any]:
        """The ``MediaAsset`` the editor's ``uploadArticleImage`` creates for this file."""
        row: dict[str, Any] = {
            "id": media_id_for(item_id, self.src_path),
            "itemId": item_id,
            "type": "image",
            "role": "body",
            "sortKey": f"{self.position:03d}#{self.src_path}",
            "storagePath": self.storage_path,
            "alt": self.filename,
            "metadata": to_aws_json(
                {"srcPath": self.src_path, "sha256": self.sha256, "bytes": self.size, "contentType": self.content_type}
            ),
        }
        if self.width is not None and self.height is not None:
            row["width"], row["height"] = self.width, self.height
        return row


@dataclass
class StoryImagePlan:
    body: str  # the body with src/srcDark rewritten
    images: list[PlannedStoryImage] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)  # local-looking references not found under the directory
    notes: list[str] = field(default_factory=list)

    def media_rows(self, item_id: str) -> list[dict[str, Any]]:
        return [image.media_row(item_id) for image in self.images]


def _is_local_reference(reference: str) -> bool:
    lowered = reference.strip().lower()
    if not lowered or lowered.startswith(("http://", "https://", "data:", "//", "/", "#", "mailto:")):
        return False
    return ":" not in lowered.split("/", 1)[0]


def _resolve_under(root: Path, reference: str) -> Path | None:
    resolved_root = root.resolve()
    candidate = (resolved_root / reference).resolve()
    if resolved_root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def _svg_dimensions(data: bytes) -> tuple[float, float] | None:
    tag = _SVG_SIZE_RE.search(data[:4096].decode("utf-8", errors="ignore"))
    if not tag:
        return None
    text = tag.group(0)

    def number(name: str) -> float | None:
        found = re.search(r"\b%s\s*=\s*[\"']\s*([0-9.]+)\s*(?:px)?\s*[\"']" % name, text)
        return float(found.group(1)) if found else None

    width, height = number("width"), number("height")
    if width and height:
        return width, height
    box = re.search(r"viewBox\s*=\s*[\"']\s*[-0-9.]+[\s,]+[-0-9.]+[\s,]+([0-9.]+)[\s,]+([0-9.]+)\s*[\"']", text)
    return (float(box.group(1)), float(box.group(2))) if box else None


def read_dimensions(path: Path, data: bytes) -> tuple[int, int] | tuple[float, float] | None:
    if path.suffix.lower() == ".svg":
        return _svg_dimensions(data)
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as image:
            return image.width, image.height
    except Exception:
        return None


def _scan_references(body: str) -> list[tuple[int, int, str, str]]:
    """``(start, end, kind, text)`` of every ``::image{}`` line and ``![](...)`` outside fenced code, in order."""
    fenced: list[tuple[int, int]] = []
    open_at: int | None = None
    open_marker = ""
    for match in _FENCE_RE.finditer(body):
        marker = match.group(1)
        if open_at is None:
            open_at, open_marker = match.start(), marker[0]
        elif marker[0] == open_marker:
            fenced.append((open_at, match.end()))
            open_at = None
    if open_at is not None:
        fenced.append((open_at, len(body)))

    def in_code(position: int) -> bool:
        return any(start <= position < end for start, end in fenced)

    found: list[tuple[int, int, str, str]] = []
    for match in _IMAGE_DIRECTIVE_RE.finditer(body):
        if not in_code(match.start()):
            found.append((match.start(), match.end(), "directive", match.group(0)))
    for match in _MARKDOWN_IMAGE_RE.finditer(body):
        if not in_code(match.start()):
            found.append((match.start(), match.end(), "markdown", match.group(0)))
    return sorted(found)


def _attribute_span(directive: str, key: str) -> tuple[int, int, str] | None:
    """``(start, end, value)`` of the whole ``key="value"`` text inside a directive line."""
    for match in _ATTR_RE.finditer(directive):
        if match.group("key") == key:
            value = match.group("dq")
            if value is None:
                value = match.group("sq")
            if value is None:
                value = match.group("bare") or ""
            return match.start(), match.end(), value
    return None


def _dark_sibling(root: Path, reference: str) -> str | None:
    """``figure.png`` -> ``figure.dark.png`` first, then ``figure.dark.<other known extension>``."""
    path = Path(reference)
    suffixes = [path.suffix.lower()] + [ext for ext in sorted(IMAGE_CONTENT_TYPES) if ext != path.suffix.lower()]
    for suffix in suffixes:
        candidate = path.with_name(f"{path.stem}.dark{suffix}").as_posix()
        if _resolve_under(root, candidate) is not None:
            return candidate
    return None


def _megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB"


def plan_story_images(
    body: str,
    images_dir: Path,
    *,
    slug: str,
    tenant_id: str | None = None,
) -> StoryImagePlan:
    """Plan the uploads for ``body`` and rewrite its image references. Raises ValueError naming every bad file."""
    root = Path(images_dir)
    if not root.is_dir():
        raise ValueError(f"--images {root}: not a directory.")
    problems: list[str] = []
    plan = StoryImagePlan(body=body)
    taken: set[str] = set()
    by_path: dict[Path, PlannedStoryImage] = {}

    def add(reference: str, local: Path, role: str, paired_with: str | None = None) -> PlannedStoryImage | None:
        existing = by_path.get(local)
        if existing is not None:
            return existing
        label = f"{reference} ({local.name})" if reference != local.name else reference
        content_type = IMAGE_CONTENT_TYPES.get(local.suffix.lower())
        if content_type is None:
            problems.append(f"{label}: unsupported file type; choose a {ALLOWED_TYPES_TEXT} image.")
            return None
        data = local.read_bytes()
        if not data:
            problems.append(f"{label}: that file is empty.")
            return None
        if len(data) > MAX_IMAGE_BYTES:
            problems.append(f"{label}: images can be at most 10 MB (this one is {_megabytes(len(data))}).")
            return None
        dimensions = read_dimensions(local, data)
        src_path = src_path_for(slug, local.name, taken)
        taken.add(src_path)
        width, height = (None, None)
        if dimensions is not None and local.suffix.lower() != ".svg":
            width, height = int(dimensions[0]), int(dimensions[1])
        image = PlannedStoryImage(
            ref=reference,
            local_path=local,
            role=role,
            src_path=src_path,
            storage_path=tenant_stored_media_path(tenant_id, f"media/{src_path}"),
            content_type=content_type,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            width=width,
            height=height,
            paired_with=paired_with,
            position=len(plan.images) + 1,
            ratio=None if not dimensions or not dimensions[1] else dimensions[0] / dimensions[1],
        )
        plan.images.append(image)
        by_path[local] = image
        return image

    def add_pair(reference: str, explicit_dark: str | None, allow_pairing: bool) -> tuple[PlannedStoryImage | None, PlannedStoryImage | None]:
        local = _resolve_under(root, reference)
        if local is None:
            return None, None
        light = add(reference, local, "light")
        dark_reference = explicit_dark
        if dark_reference is None and allow_pairing:
            dark_reference = _dark_sibling(root, reference)
        dark = None
        if dark_reference is not None and dark_reference.lower() != "none":
            dark_local = _resolve_under(root, dark_reference)
            if dark_local is None:
                problems.append(f"{dark_reference}: the dark version of {reference} was not found under {root}.")
            else:
                dark = add(dark_reference, dark_local, "dark", paired_with=reference)
        if light is not None and dark is not None:
            _check_aspect(light, dark, problems)
        return light, dark

    pieces: list[str] = []
    cursor = 0
    for start, end, kind, text in _scan_references(body):
        pieces.append(body[cursor:start])
        cursor = end
        if kind == "directive":
            rewritten = _rewrite_directive(text, root, add_pair, plan)
        else:
            rewritten = _rewrite_markdown(text, root, add_pair, plan)
        pieces.append(rewritten)
    pieces.append(body[cursor:])
    if problems:
        raise ValueError("\n".join(problems))
    plan.body = "".join(pieces)
    return plan


def _check_aspect(light: PlannedStoryImage, dark: PlannedStoryImage, problems: list[str]) -> None:
    light_ratio, dark_ratio = light.ratio, dark.ratio
    if light_ratio is None or dark_ratio is None:
        unknown = light if light_ratio is None else dark
        problems.append(f"{unknown.ref}: cannot read its dimensions, so the light/dark aspect ratio cannot be checked.")
        return
    if abs(light_ratio - dark_ratio) / light_ratio > DARK_ASPECT_TOLERANCE:
        problems.append(
            f"{dark.ref}: the dark version of {light.ref} has a different aspect ratio "
            f"({_shape(dark)} vs {_shape(light)}); the two files must have the same proportions (within 0.5%)."
        )


def _shape(image: PlannedStoryImage) -> str:
    if image.width and image.height:
        return f"{image.width}x{image.height}"
    return f"ratio {image.ratio:.3f}" if image.ratio else "unknown size"


def _rewrite_directive(text: str, root: Path, add_pair: Callable, plan: StoryImagePlan) -> str:
    src = _attribute_span(text, "src")
    if src is None or not _is_local_reference(src[2]):
        return text
    dark_attribute = _attribute_span(text, "srcDark")
    explicit_dark = None
    if dark_attribute is not None and (_is_local_reference(dark_attribute[2]) or dark_attribute[2].strip().lower() == "none"):
        explicit_dark = dark_attribute[2]
    light, dark = add_pair(src[2], explicit_dark, dark_attribute is None)
    if light is None and _resolve_under(root, src[2]) is None:
        plan.unresolved.append(src[2])
        return text
    if light is None:
        return text
    edits = [(src[0], src[1], f'src="{light.src_path}"')]
    if dark is not None:
        if dark_attribute is not None:
            edits.append((dark_attribute[0], dark_attribute[1], f'srcDark="{dark.src_path}"'))
        else:
            edits.append((src[1], src[1], f' srcDark="{dark.src_path}"'))
    for begin, finish, replacement in sorted(edits, reverse=True):
        text = text[:begin] + replacement + text[finish:]
    return text


def _rewrite_markdown(text: str, root: Path, add_pair: Callable, plan: StoryImagePlan) -> str:
    match = _MARKDOWN_IMAGE_RE.fullmatch(text)
    reference = match.group("src")
    if not _is_local_reference(reference):
        return text
    light, dark = add_pair(reference, None, True)
    if light is None:
        if _resolve_under(root, reference) is None:
            plan.unresolved.append(reference)
        return text
    if dark is not None:
        plan.notes.append(
            f"{dark.ref}: uploaded next to {light.ref}, but a Markdown image has no srcDark; "
            "use an ::image{} directive for the dark picture to show."
        )
    return f"![{match.group('alt')}]({light.src_path}{match.group('title') or ''})"


# -- uploads and auth lanes ---------------------------------------------------------------------------------------

def user_identity() -> tuple[str, str]:
    """``(Cognito ID token, issuer)`` of the signed-in user for this process's GraphQL endpoint."""
    from .cli_user_auth import config_for_endpoint, selected_headers
    from .env import graphql_endpoint

    endpoint = graphql_endpoint()
    headers = selected_headers(endpoint)
    if not headers or not headers.get("Authorization"):
        raise ValueError("No signed-in user session; run `papyrus login <site>` first.")
    return headers["Authorization"], config_for_endpoint(endpoint).issuer


def identity_pool_id(explicit: str | None = None) -> str:
    from .env import identity_pool_id_from_amplify_outputs

    found = (explicit or "").strip() or identity_pool_id_from_amplify_outputs()
    if not found:
        raise ValueError(
            "No identity pool configured: the signed-in user lane needs the site's Cognito identity pool to upload "
            "to S3. Pass --identity-pool-id, set PAPYRUS_IDENTITY_POOL_ID, or provide amplify_outputs.json."
        )
    return found


def _cognito_identity_client(region: str) -> Any:
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    return boto3.client("cognito-identity", region_name=region, config=Config(signature_version=UNSIGNED))


def _s3_client(credentials: dict[str, str], region: str | None) -> Any:
    import boto3

    return boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretKey"],
        aws_session_token=credentials["SessionToken"],
    )


def user_lane_s3_client(pool_id: str | None = None) -> Any:
    """An S3 client holding the signed-in user's temporary identity-pool credentials (never AWS profile keys)."""
    id_token, issuer = user_identity()
    match = re.fullmatch(r"https://cognito-idp\.([a-z0-9-]+)\.amazonaws\.com/([\w-]+)", issuer)
    if not match:
        raise ValueError(f"Cannot derive the Cognito region and user pool from issuer {issuer!r}.")
    region, user_pool = match.groups()
    resolved_pool = identity_pool_id(pool_id)
    pool_region = resolved_pool.split(":", 1)[0] if ":" in resolved_pool else region
    logins = {f"cognito-idp.{region}.amazonaws.com/{user_pool}": id_token}
    identity = _cognito_identity_client(pool_region)
    identity_id = identity.get_id(IdentityPoolId=resolved_pool, Logins=logins)["IdentityId"]
    credentials = identity.get_credentials_for_identity(IdentityId=identity_id, Logins=logins)["Credentials"]
    return _s3_client(credentials, region)


def open_media_store(bucket: str | None = None, pool_id: str | None = None) -> Any:
    """The S3 store for this process's lane: identity-pool credentials for a signed-in user, else the AWS credentials."""
    from .media_store import S3MediaStore
    from .user_auth_mode import user_auth_requested

    if user_auth_requested():
        return S3MediaStore(bucket, client=user_lane_s3_client(pool_id))
    return S3MediaStore(bucket)


def upload_planned_images(plan: StoryImagePlan, store: Any) -> list[tuple[PlannedStoryImage, str]]:
    """Put every planned file in the store; an object already there with the same content is left alone."""
    return [
        (image, store.put(image.storage_path, image.local_path, content_type=image.content_type, sha256=image.sha256))
        for image in plan.images
    ]


def plan_lines(plan: StoryImagePlan, item_id: str) -> list[str]:
    lines = []
    for image in plan.images:
        pairing = f"\tdark of {image.paired_with}" if image.paired_with else ""
        lines.append(
            "\t".join(
                ["stories", "save-version", "image", image.role, image.ref, media_id_for(item_id, image.src_path),
                 image.storage_path, f"{image.size} bytes"]
            )
            + pairing
        )
    lines += [f"stories\tsave-version\timage-unresolved\t{ref}\tnot found under --images; left unchanged" for ref in plan.unresolved]
    lines += [f"stories\tsave-version\timage-note\t{note}" for note in plan.notes]
    return lines
