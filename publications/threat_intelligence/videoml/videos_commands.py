from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from papyrus_content.env import load_dotenv
from papyrus_content.options import normalize_positive_integer, normalize_string, parse_boolean_option, parse_options
from publications.threat_intelligence.videoml.video_pipeline import (
    article_output_mp4,
    edition_overview_output_mp4,
    lead_video_articles,
    load_ti_seed_articles,
    load_ti_seed_payload,
    probe_openai_key,
    render_edition_overview,
    render_video,
    THEMES,
)

DEFAULT_RENDER_JOBS = 3


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


def _render_unit_sequential(
    label: str,
    render_fn: Callable[[str], Any],
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


def videos_render(flags: list[str]) -> None:
    options = parse_options(flags)
    slug = normalize_string(options.get("article"))
    edition_overview = parse_boolean_option(options.get("edition-overview"), False, "--edition-overview")
    theme_option = parse_theme_option(options.get("theme"))
    themes = resolve_themes(theme_option)
    if edition_overview:
        probe = parse_boolean_option(options.get("probe-only"), False, "--probe-only")
        if probe:
            print(json.dumps({"probe": probe_openai_key()}, indent=2))
            return
        probe_openai_key()
        rendered: list[dict[str, str]] = []
        for theme in themes:
            output = render_edition_overview(theme=theme)
            rendered.append({"slug": "edition-overview", "theme": theme, "output": str(output)})
        print(json.dumps({"ok": True, "videos": rendered}, indent=2))
        return

    if not slug:
        raise ValueError("videos render requires --article <slug> or --edition-overview.")

    articles = load_ti_seed_articles()
    article = next((entry for entry in articles if str(entry.get("slug", "")).strip() == slug), None)
    if article is None:
        raise ValueError(f"Article '{slug}' was not found in the Threat Intelligence seed edition.")

    probe = parse_boolean_option(options.get("probe-only"), False, "--probe-only")
    if probe:
        print(json.dumps({"probe": probe_openai_key()}, indent=2))
        return

    probe_openai_key()
    rendered: list[dict[str, str]] = []
    for theme in themes:
        output = render_video(article, theme=theme)
        rendered.append({"slug": slug, "theme": theme, "output": str(output)})
    print(json.dumps({"ok": True, "videos": rendered}, indent=2))


def videos_seed(flags: list[str]) -> None:
    options = parse_options(flags)
    probe_only = parse_boolean_option(options.get("probe-only"), False, "--probe-only")
    if probe_only:
        print(json.dumps({"probe": probe_openai_key()}, indent=2))
        return

    theme_option = parse_theme_option(options.get("theme"))
    themes = resolve_themes(theme_option)
    jobs = parse_jobs_option(options.get("jobs"))
    probe_openai_key()
    payload = load_ti_seed_payload()

    # Build render units: (label, render_fn).
    # Each unit renders its themes sequentially (dark before light for TTS cache reuse),
    # but different units run in parallel via ThreadPoolExecutor.
    units: list[tuple[str, Callable[[str], Any]]] = [
        ("edition-overview", lambda theme: render_edition_overview(payload=payload, theme=theme)),
    ]
    for article in lead_video_articles():
        article_slug = str(article.get("slug", "")).strip()
        article_copy = article
        units.append((article_slug, lambda theme, a=article_copy: render_video(a, theme=theme)))

    print(f"Rendering {len(units)} videos x {len(themes)} theme(s) with {jobs} parallel jobs", flush=True)

    print_lock = threading.Lock()
    rendered: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        future_to_label = {
            pool.submit(_render_unit_sequential, label, render_fn, themes, print_lock): label
            for label, render_fn in units
        }
        for future in as_completed(future_to_label):
            label = future_to_label[future]
            try:
                results = future.result()
                rendered.extend(results)
            except Exception as exc:
                errors.append({"slug": label, "error": str(exc)})
                with print_lock:
                    print(f"  [FAIL]  {label}: {exc}", flush=True)

    # Sort results by the original unit order for deterministic output.
    label_order = {label: i for i, (label, _) in enumerate(units)}
    rendered.sort(key=lambda entry: (label_order.get(entry["slug"], 999), entry["theme"]))

    print(
        json.dumps(
            {
                "ok": len(errors) == 0,
                "count": len(rendered),
                "videos": rendered,
                **({"errors": errors} if errors else {}),
            },
            indent=2,
        )
    )


def videos_attach(flags: list[str]) -> None:
    options = parse_options(flags)
    slug = normalize_string(options.get("article"))
    if not slug:
        raise ValueError("videos attach requires --article <slug>.")

    load_dotenv()
    from .graphql_authoring import create_authoring_client
    from .records import apply_record_changes, build_record_changes_targeted_by_id
    from .seed_edition import build_seed_edition_records, load_seed_payload, resolve_seed_content_path

    seed_path, _profile = resolve_seed_content_path({"profile": "threat-intelligence"})
    payload = load_seed_payload(seed_path)
    article = next((entry for entry in payload["articles"] if str(entry.get("slug", "")).strip() == slug), None)
    if article is None:
        raise ValueError(f"Article '{slug}' was not found in seed edition content.")

    mp4 = article_output_mp4(article)
    if not mp4.exists():
        raise ValueError(f"Rendered video not found at {mp4}. Run `poetry run papyrus videos render --article {slug}` first.")

    records = build_seed_edition_records(payload)
    client, _claims = create_authoring_client()
    changes = build_record_changes_targeted_by_id(client, records)
    apply_record_changes(client, changes)
    print(json.dumps({"ok": True, "slug": slug, "attachedVia": "content seed-edition records refresh"}, indent=2))
