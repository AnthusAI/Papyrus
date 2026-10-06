from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from papyrus_content.options import normalize_positive_integer, normalize_string, parse_boolean_option, parse_options
from papyrus_content.record_helpers import to_aws_json

from .config import SUPPORTED_VOICEOVER_PROVIDERS, THEMES, VideoConfig, load_video_config, resolve_video_config_path
from .dsl import fetch_item_by_slug, resolve_dsl_for_render
from .pipeline import (
    output_mp4_path,
    probe_voiceover_provider,
    render_video,
    resolve_video_voiceover_provider,
    resolve_voiceover_defaults,
)

DEFAULT_RENDER_JOBS = 3
VIDEO_STORAGE_PREFIX = "media/videos"
VIDEO_CONTENT_TYPE = "video/mp4"


def parse_theme_option(value: object) -> str:
    raw = normalize_string(value)
    if raw is None:
        return "both"
    normalized = raw.lower()
    if normalized not in ("dark", "light", "both"):
        raise ValueError("--theme must be 'dark', 'light', or 'both'.")
    return normalized


def resolve_themes(theme: str) -> list[str]:
    return list(THEMES) if theme == "both" else [theme]


def parse_jobs_option(value: object) -> int:
    parsed = normalize_positive_integer(value, "--jobs")
    return parsed if parsed is not None else DEFAULT_RENDER_JOBS


def parse_provider_option(value: object, config: VideoConfig) -> str:
    raw = normalize_string(value)
    if raw is None:
        return resolve_video_voiceover_provider(config)
    normalized = raw.lower()
    if normalized not in SUPPORTED_VOICEOVER_PROVIDERS:
        raise ValueError(f"--provider must be one of: {', '.join(SUPPORTED_VOICEOVER_PROVIDERS)}")
    return normalized


def load_publication_video_config() -> VideoConfig:
    return load_video_config(resolve_video_config_path())


def create_default_client() -> Any:
    from papyrus_content.graphql_authoring import create_authoring_client

    client, _claims = create_authoring_client()
    return client


def render_theme_variants(
    label: str,
    render_fn: Callable[[str], Path],
    themes: list[str],
    print_lock: threading.Lock,
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for theme in themes:
        with print_lock:
            print(f"  [start] {label} ({theme})", flush=True)
        output = render_fn(theme)
        with print_lock:
            print(f"  [done]  {label} ({theme}) -> {output}", flush=True)
        results.append({"slug": label, "theme": theme, "output": str(output)})
    return results


def videos_render(flags: list[str], *, client: Any = None, config: VideoConfig | None = None) -> None:
    options = parse_options(flags)
    slug = normalize_string(options.get("article"))
    if not slug:
        raise ValueError("videos render requires --article <slug>.")
    video_config = config or load_publication_video_config()
    themes = resolve_themes(parse_theme_option(options.get("theme")))
    from_article = parse_boolean_option(options.get("from-article"), False, "--from-article")
    provider = parse_provider_option(options.get("provider"), video_config)
    if parse_boolean_option(options.get("probe-only"), False, "--probe-only"):
        print(json.dumps({"probe": probe_voiceover_provider(provider)}, indent=2))
        return
    authoring_client = client or create_default_client()
    probe_voiceover_provider(provider)
    rendered = [
        {
            "slug": slug,
            "theme": theme,
            "output": str(render_video(video_config, authoring_client, slug, theme=theme, from_article=from_article, provider=provider)),
        }
        for theme in themes
    ]
    print(json.dumps({"ok": True, "provider": provider, "videos": rendered}, indent=2))


def seed_dry_run_plan(
    video_config: VideoConfig,
    client: Any,
    slugs: list[str],
    themes: list[str],
    from_article: bool,
    provider: str,
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for slug in slugs:
        for theme in themes:
            dsl_xml = resolve_dsl_for_render(
                client=client,
                config=video_config,
                target_slug=slug,
                theme=theme,
                from_article=from_article,
                voiceover_defaults=resolve_voiceover_defaults,
                provider=provider,
            )
            plan.append(
                {
                    "slug": slug,
                    "theme": theme,
                    "output": str(output_mp4_path(video_config, slug, theme)),
                    "dslCharacters": len(dsl_xml),
                }
            )
    return plan


def videos_seed(flags: list[str], *, client: Any = None, config: VideoConfig | None = None) -> None:
    options = parse_options(flags)
    video_config = config or load_publication_video_config()
    provider = parse_provider_option(options.get("provider"), video_config)
    if parse_boolean_option(options.get("probe-only"), False, "--probe-only"):
        print(json.dumps({"probe": probe_voiceover_provider(provider)}, indent=2))
        return

    explicit_slug = normalize_string(options.get("slug"))
    slugs = [explicit_slug] if explicit_slug else list(video_config.lead_slugs)
    if not slugs:
        raise ValueError("videos seed needs --slug <slug> or leadSlugs in the video config.")
    themes = resolve_themes(parse_theme_option(options.get("theme")))
    jobs = parse_jobs_option(options.get("jobs"))
    from_article = parse_boolean_option(options.get("from-article"), False, "--from-article")
    authoring_client = client or create_default_client()

    if parse_boolean_option(options.get("dry-run"), False, "--dry-run"):
        plan = seed_dry_run_plan(video_config, authoring_client, slugs, themes, from_article, provider)
        print(json.dumps({"ok": True, "dryRun": True, "provider": provider, "plan": plan}, indent=2))
        return

    probe_voiceover_provider(provider)
    print(f"Rendering {len(slugs)} videos x {len(themes)} theme(s) with {jobs} parallel jobs", flush=True)
    print_lock = threading.Lock()
    rendered: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        future_to_slug = {
            pool.submit(
                render_theme_variants,
                slug,
                lambda theme, slug=slug: render_video(
                    video_config, authoring_client, slug, theme=theme, from_article=from_article, provider=provider
                ),
                themes,
                print_lock,
            ): slug
            for slug in slugs
        }
        for future in as_completed(future_to_slug):
            slug = future_to_slug[future]
            try:
                rendered.extend(future.result())
            except Exception as error:
                errors.append({"slug": slug, "error": str(error)})
                with print_lock:
                    print(f"  [FAIL]  {slug}: {error}", flush=True)

    order = {slug: index for index, slug in enumerate(slugs)}
    rendered.sort(key=lambda entry: (order.get(entry["slug"], len(order)), entry["theme"]))
    print(
        json.dumps(
            {
                "ok": not errors,
                "provider": provider,
                "count": len(rendered),
                "videos": rendered,
                **({"errors": errors} if errors else {}),
            },
            indent=2,
        )
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def video_storage_path(slug: str, theme: str) -> str:
    suffix = "-light" if theme == "light" else ""
    return f"{VIDEO_STORAGE_PREFIX}/{slug}{suffix}.mp4"


def attach_rendered_video(client: Any, store: Any, config: VideoConfig, slug: str) -> dict[str, Any]:
    item = fetch_item_by_slug(client, slug)
    if item is None:
        raise ValueError(f"No item with slug '{slug}'.")
    dark_mp4 = output_mp4_path(config, slug, "dark")
    if not dark_mp4.is_file():
        raise ValueError(f"Rendered video not found at {dark_mp4}. Run `papyrus videos render --article {slug}` first.")

    uploads: dict[str, str] = {}
    theme_variants: dict[str, dict[str, str]] = {}
    for theme in THEMES:
        local_path = output_mp4_path(config, slug, theme)
        if not local_path.is_file():
            continue
        storage_path = video_storage_path(slug, theme)
        uploads[storage_path] = store.put(
            storage_path, local_path, content_type=VIDEO_CONTENT_TYPE, sha256=file_sha256(local_path)
        )
        theme_variants[theme] = {"storagePath": storage_path}

    item_id = str(item["id"])
    headline = str(item.get("headline") or item.get("title") or slug)
    existing = [
        row
        for row in client.list_by_index("mediaAssetsByItemAndSortKey", item_id)
        if row.get("type") == "video" and "lead" in str(row.get("role") or "")
    ]
    media_id = str(existing[0]["id"]) if existing else f"media-{slug}-video-lead"
    metadata = {"themeVariants": theme_variants} if "light" in theme_variants else {}
    payload = {
        "id": media_id,
        "itemId": item_id,
        "type": "video",
        "role": "lead",
        "sortKey": f"video#{slug}",
        "storagePath": video_storage_path(slug, "dark"),
        "alt": f"Video for {headline}",
        "metadata": to_aws_json(metadata),
    }
    action = client.upsert("MediaAsset", payload)
    return {"ok": True, "slug": slug, "mediaAssetId": media_id, "media": action, "uploads": uploads}


def create_default_media_store() -> Any:
    from papyrus_content.media_store import S3MediaStore

    return S3MediaStore()


def videos_attach(
    flags: list[str],
    *,
    client: Any = None,
    store: Any = None,
    config: VideoConfig | None = None,
) -> None:
    options = parse_options(flags)
    slug = normalize_string(options.get("article"))
    if not slug:
        raise ValueError("videos attach requires --article <slug>.")
    video_config = config or load_publication_video_config()
    result = attach_rendered_video(
        client or create_default_client(),
        store or create_default_media_store(),
        video_config,
        slug,
    )
    print(json.dumps(result, indent=2))
