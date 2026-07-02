from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from .env import PAPYRUS_ROOT, storage_bucket_from_amplify_outputs
from .graphql_authoring import PapyrusGraphQLAuthoringClient, create_authoring_client
from .options import normalize_string, parse_boolean_option, parse_options, resolve_mutation_apply
from .reader_revalidation import trigger_reader_cache_revalidation
from .records import apply_record_changes, build_record_changes_targeted_by_id

SEED_CONTENT_PATH = PAPYRUS_ROOT / "amplify" / "seed" / "seed-edition-content.json"
DEFAULT_SEED_PROFILE = "default"
SEED_PROFILE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def seed_edition_content(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "content seed-edition")
    seed_path, seed_profile = resolve_seed_content_path(options)
    upload_media = parse_boolean_option(options.get("upload-media"), default=True, label="--upload-media")
    bucket = normalize_string(options.get("bucket")) or storage_bucket_from_amplify_outputs()
    if apply and upload_media and not bucket:
        raise ValueError("Could not resolve storage bucket. Pass --bucket or refresh amplify_outputs.json.")

    payload = load_seed_payload(seed_path)
    records = build_seed_edition_records(payload)
    client, _claims = create_authoring_client()
    changes = build_record_changes_targeted_by_id(client, records)
    stale_edition_item_records = list_stale_seed_edition_item_records(client, payload, records)
    stale_media_records = list_stale_seed_media_records(client, payload)
    counts = summarize_changes(changes)
    result = {
        "ok": True,
        "command": "content seed-edition",
        "seedPath": str(seed_path),
        "seedProfile": seed_profile,
        "editionId": payload["id"],
        "articleCount": len(payload["articles"]),
        "recordCount": len(records),
        "changes": counts,
        "deleteStaleEditionItems": summarize_stale_media(stale_edition_item_records),
        "deleteStaleMedia": summarize_stale_media(stale_media_records),
        "apply": apply,
    }
    if apply:
        if upload_media:
            upload_seed_media(payload, bucket=str(bucket))
        delete_stale_seed_records(client, stale_edition_item_records)
        delete_stale_seed_media_records(client, stale_media_records)
        apply_record_changes(client, changes)
        result["applied"] = True
        article_slugs = [str(article.get("slug", "")).strip() for article in payload.get("articles", [])]
        article_slugs = [slug for slug in article_slugs if slug]
        revalidation = trigger_reader_cache_revalidation(
            edition_date=str(payload["publishDate"]),
            article_slugs=article_slugs,
            item_slugs=article_slugs,
        )
        if revalidation is not None:
            result["readerRevalidation"] = revalidation
    if options.get("json"):
        print(json.dumps(result, indent=2))
    else:
        print_seed_summary(result)


def resolve_seed_content_path(options: dict[str, Any]) -> tuple[Path, str]:
    explicit_seed = normalize_string(options.get("seed"))
    if explicit_seed:
        seed_path = Path(explicit_seed)
        if not seed_path.is_absolute():
            seed_path = PAPYRUS_ROOT / seed_path
        return seed_path, normalize_string(options.get("profile")) or "custom"

    profile_id = (
        normalize_string(options.get("profile"))
        or normalize_string(os.environ.get("PAPYRUS_SEED_PROFILE"))
        or DEFAULT_SEED_PROFILE
    ).lower()
    if not SEED_PROFILE_PATTERN.match(profile_id):
        raise ValueError(f"Invalid seed profile '{profile_id}'. Use lowercase letters, numbers, '-', or '_'.")

    if profile_id == DEFAULT_SEED_PROFILE:
        return SEED_CONTENT_PATH, profile_id

    candidates = [
        PAPYRUS_ROOT / "publications" / profile_id.replace("-", "_") / "seed" / "seed-edition-content.json",
        PAPYRUS_ROOT / "amplify" / "seed" / "profiles" / profile_id / "seed-edition-content.json",
        SEED_CONTENT_PATH,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate, profile_id
    raise ValueError(
        f"Could not find seed edition content for profile '{profile_id}'. "
        f"Checked: {', '.join(str(candidate) for candidate in candidates)}"
    )


def load_seed_payload(path: Path = SEED_CONTENT_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1:
        raise ValueError(f"Unsupported seed edition schema in {path}.")
    articles = payload.get("articles")
    if not isinstance(articles, list) or not articles:
        raise ValueError(f"Seed edition content in {path} must include articles.")
    for field in ("id", "slug", "title", "description", "publishDate"):
        if not normalize_string(payload.get(field)):
            raise ValueError(f"Seed edition content in {path} is missing {field}.")
    return payload


def build_seed_edition_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    edition_config = seed_edition_config(payload)
    ordered_articles = order_articles(payload["articles"], edition_config["articleOrder"])
    records: list[dict[str, Any]] = []
    edition_record = with_version_fields(
        {
            "id": edition_config["id"],
            "slug": edition_config["slug"],
            "title": edition_config["title"],
            "status": "published",
            "editionDate": edition_config["publishDate"],
            "publishedAt": edition_config["publishedAt"],
            "description": edition_config["description"],
            "layoutPlan": to_aws_json(edition_config["layoutPlan"]),
            "metadata": to_aws_json(edition_config["metadata"]),
        },
        lineage_id=edition_config["id"],
        version_created_at=edition_config["publishedAt"],
        version_created_by="python-seed",
        change_reason="fixture seed",
    )
    records.append(record("Edition", edition_record))
    records.append(
        record(
            "PublishedEdition",
            {
                "id": published_edition_id(edition_config["id"]),
                "sourceEditionId": edition_record["id"],
                "editionLineageId": edition_record["lineageId"],
                "versionNumber": edition_record["versionNumber"],
                "slug": edition_config["slug"],
                "title": edition_config["title"],
                "status": "published",
                "editionDate": edition_config["publishDate"],
                "publishedAt": edition_config["publishedAt"],
                "description": edition_config["description"],
                "layoutPlan": to_aws_json(edition_config["layoutPlan"]),
                "metadata": to_aws_json(edition_config["metadata"]),
            },
        )
    )
    for index, article in enumerate(ordered_articles):
        records.extend(seed_article_records(article, index, edition_config))
    return records


def seed_edition_config(payload: dict[str, Any]) -> dict[str, Any]:
    publish_date = str(payload["publishDate"])
    item_ids = [article["slug"] for article in payload["articles"]]
    return {
        "id": payload["id"],
        "slug": payload["slug"],
        "title": payload["title"],
        "description": payload["description"],
        "publishDate": publish_date,
        "publishedAt": f"{publish_date}T12:00:00.000Z",
        "metadata": {
            "source": "fixture-seed",
            "suppressNewsDeskAppendix": payload.get("suppressNewsDeskAppendix") is True,
            **(
                {"editionVideo": build_edition_video_metadata(payload, payload["video"])}
                if isinstance(payload.get("video"), dict)
                else {}
            ),
        },
        "articleOrder": item_ids,
        "layoutPlan": apply_seed_house_ads(create_seed_edition_layout_plan(payload["articles"]), payload.get("houseAds")),
    }


def apply_seed_house_ads(layout_plan: dict[str, Any], house_ads: Any) -> dict[str, Any]:
    if not isinstance(house_ads, list) or not house_ads:
        return layout_plan
    for ad in house_ads:
        if not isinstance(ad, dict):
            continue
        page_number = ad.get("pageNumber")
        label = normalize_string(ad.get("label"))
        ad_id = normalize_string(ad.get("id"))
        if page_number is None or not label or not ad_id:
            continue
        page = next((entry for entry in layout_plan.get("pages", []) if entry.get("pageNumber") == page_number), None)
        regions = page.get("regions") if isinstance(page, dict) else None
        if not isinstance(regions, list) or not regions:
            continue
        region = regions[0]
        blocks = region.get("blocks")
        if not isinstance(blocks, list):
            continue
        blocks.append(
            {
                "id": ad_id,
                "type": "adBlock",
                "presetId": normalize_string(ad.get("presetId")) or "ad.region",
                "required": False,
                "label": label,
            }
        )
    return layout_plan


def seed_article_records(article: dict[str, Any], index: int, edition_config: dict[str, Any]) -> list[dict[str, Any]]:
    item_id = f"item-{article['slug']}"
    section_slug = slugify(article.get("section") or "")
    tag_id = f"tag-{section_slug}"
    sort_key = f"{index + 1:03d}#{article['slug']}"
    editorial_payload: dict[str, Any] = {}
    excerpt = normalize_string(article.get("excerpt"))
    if excerpt:
        editorial_payload["customExcerpt"] = excerpt

    item_record = with_version_fields(
        {
            "id": item_id,
            "type": "article",
            "status": "published",
            "typeStatus": "article#published",
            "slug": article["slug"],
            "shortSlug": article.get("shortSlug"),
            "section": article.get("section"),
            "sectionStatus": f"{section_slug}#published",
            "title": article.get("headline"),
            "headline": article.get("headline"),
            "deck": article.get("deck"),
            "body": article.get("body") or [],
            "byline": article.get("byline"),
            "dateline": article.get("dateline"),
            "publishedAt": edition_config["publishedAt"],
            "editionDate": edition_config["publishDate"],
            "sortTitle": article.get("headline"),
            "pullQuotes": article.get("pullQuotes") or [],
            "layout": to_aws_json({"source": "fixture"}),
            "editorial": to_aws_json(editorial_payload),
        },
        lineage_id=item_id,
        version_created_at=edition_config["publishedAt"],
        version_created_by="python-seed",
        change_reason="fixture seed",
    )
    records = [
        record("Item", item_record),
        record(
            "PublishedItem",
            {
                "id": published_item_id(item_id),
                "sourceItemId": item_record["id"],
                "itemLineageId": item_record["lineageId"],
                "versionNumber": item_record["versionNumber"],
                "type": "article",
                "status": "published",
                "typeStatus": "article#published",
                "slug": article["slug"],
                "shortSlug": article.get("shortSlug"),
                "section": article.get("section"),
                "sectionStatus": f"{section_slug}#published",
                "title": article.get("headline"),
                "headline": article.get("headline"),
                "deck": article.get("deck"),
                "body": article.get("body") or [],
                "byline": article.get("byline"),
                "dateline": article.get("dateline"),
                "publishedAt": edition_config["publishedAt"],
                "editionDate": edition_config["publishDate"],
                "sortTitle": article.get("headline"),
                "pullQuotes": article.get("pullQuotes") or [],
                "layout": to_aws_json({"source": "fixture"}),
                "editorial": to_aws_json(editorial_payload),
            },
        ),
        record("Tag", {"id": tag_id, "slug": section_slug, "label": article.get("section"), "type": "section"}),
        record(
            "ItemTag",
            {
                "id": f"item-tag-{article['slug']}-{section_slug}",
                "itemId": item_id,
                "tagId": tag_id,
                "itemType": "article",
                "itemStatus": "published",
                "tagSlug": section_slug,
                "publishedAt": edition_config["publishedAt"],
            },
        ),
        record(
            "EditionItem",
            {
                "id": f"{edition_config['id']}-{article['slug']}",
                "editionId": edition_config["id"],
                "editionLineageId": edition_config["id"],
                "itemId": item_id,
                "itemLineageId": item_id,
                "placementKey": f"front:{index + 1}",
                "sortKey": sort_key,
                "pageNumber": 1,
                "priority": index + 1,
                "metadata": to_aws_json({}),
            },
        ),
        record(
            "PublishedEditionItem",
            {
                "id": f"{published_edition_id(edition_config['id'])}-{article['slug']}",
                "publishedEditionId": published_edition_id(edition_config["id"]),
                "publishedItemId": published_item_id(item_id),
                "sourceEditionItemId": f"{edition_config['id']}-{article['slug']}",
                "sourceEditionId": edition_config["id"],
                "sourceItemId": item_id,
                "editionLineageId": edition_config["id"],
                "itemLineageId": item_id,
                "placementKey": f"front:{index + 1}",
                "sortKey": sort_key,
                "pageNumber": 1,
                "priority": index + 1,
                "metadata": to_aws_json({}),
            },
        ),
    ]
    for asset_index, asset in enumerate(article_image_assets(article)):
        media_id = f"media-{article['slug']}-{asset_index}"
        media_sort_key = f"{asset_index + 1:03d}#{asset['id']}"
        uploaded = seed_image_upload_metadata(article, asset, asset_index)
        theme_variants = seed_image_theme_variants_metadata(article, asset, asset_index)
        common = {
            "type": "image",
            "role": ",".join(asset.get("roles") or ["lead", "continuation", "continuationInset"]),
            "sortKey": media_sort_key,
            "storagePath": uploaded["storagePath"],
            "externalUrl": asset.get("src"),
            "alt": asset.get("alt"),
            "caption": asset.get("caption") or asset.get("credit"),
            "credit": asset.get("credit"),
            "width": uploaded.get("width"),
            "height": uploaded.get("height"),
            "aspectRatio": nested_get(asset, "layout", "aspectRatio"),
            "focalX": nested_get(asset, "layout", "focalPoint", "x"),
            "focalY": nested_get(asset, "layout", "focalPoint", "y"),
            "minHeight": nested_get(asset, "layout", "minHeight"),
            "preferredHeight": nested_get(asset, "layout", "preferredHeight"),
            "maxHeight": nested_get(asset, "layout", "maxHeight"),
            "crop": nested_get(asset, "layout", "crop"),
            "wrapsText": nested_get(asset, "layout", "wrapsText"),
            "metadata": to_aws_json(media_metadata(asset, theme_variants)),
        }
        records.append(record("MediaAsset", {"id": media_id, "itemId": item_id, **common}))
        records.append(
            record(
                "PublishedMediaAsset",
                {
                    "id": f"published-{media_id}",
                    "sourceMediaAssetId": media_id,
                    "publishedItemId": published_item_id(item_id),
                    "sourceItemId": item_id,
                    "itemLineageId": item_id,
                    **common,
                },
            )
        )

    video_asset = article_video_asset(article)
    if video_asset:
        video_index = len(list(article_image_assets(article)))
        media_id = f"media-{article['slug']}-video"
        media_sort_key = f"{video_index + 1:03d}#{article['slug']}-lead-video"
        video_common = {
            "type": "video",
            "role": "lead",
            "sortKey": media_sort_key,
            "storagePath": seed_video_upload_metadata(article, video_asset)["storagePath"],
            "externalUrl": video_asset.get("src"),
            "alt": video_asset.get("alt"),
            "caption": video_asset.get("caption") or video_asset.get("credit"),
            "credit": video_asset.get("credit"),
            "aspectRatio": 16 / 9,
            "metadata": to_aws_json(video_media_metadata(video_asset, article_slug=str(article["slug"]))),
        }
        records.append(record("MediaAsset", {"id": media_id, "itemId": item_id, **video_common}))
        records.append(
            record(
                "PublishedMediaAsset",
                {
                    "id": f"published-{media_id}",
                    "sourceMediaAssetId": media_id,
                    "publishedItemId": published_item_id(item_id),
                    "sourceItemId": item_id,
                    "itemLineageId": item_id,
                    **video_common,
                },
            )
        )
    return records


def list_stale_seed_edition_item_records(
    client: PapyrusGraphQLAuthoringClient,
    payload: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    edition_id = str(payload["id"])
    published_id = published_edition_id(edition_id)
    expected_ids: dict[str, set[str]] = {"EditionItem": set(), "PublishedEditionItem": set()}
    for record_entry in records:
        model_name = record_entry.get("modelName")
        if model_name not in expected_ids:
            continue
        record_id = normalize_string((record_entry.get("expected") or {}).get("id"))
        if record_id:
            expected_ids[str(model_name)].add(record_id)
    current = {
        "EditionItem": client.list_by_index("editionItemsByEditionAndSortKey", edition_id),
        "PublishedEditionItem": client.list_by_index("publishedEditionItemsByEditionAndSortKey", published_id),
    }
    return {
        model_name: [
            record_entry
            for record_entry in records_for_model
            if normalize_string(record_entry.get("id")) not in expected_ids[model_name]
        ]
        for model_name, records_for_model in current.items()
    }


def list_stale_seed_media_records(client: PapyrusGraphQLAuthoringClient, payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    stale = {"MediaAsset": [], "PublishedMediaAsset": []}
    for article in payload["articles"]:
        item_id = f"item-{article['slug']}"
        published_id = published_item_id(item_id)
        stale["MediaAsset"].extend(client.list_by_index("mediaAssetsByItemAndSortKey", item_id))
        stale["PublishedMediaAsset"].extend(client.list_by_index("publishedMediaAssetsByItemAndSortKey", published_id))
    return stale


def summarize_stale_media(records_by_model: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {model_name: len(records) for model_name, records in records_by_model.items()}


def delete_stale_seed_records(
    client: PapyrusGraphQLAuthoringClient,
    records_by_model: dict[str, list[dict[str, Any]]],
) -> None:
    for model_name in records_by_model:
        seen_ids: set[str] = set()
        for record_entry in records_by_model.get(model_name, []):
            record_id = normalize_string(record_entry.get("id"))
            if not record_id or record_id in seen_ids:
                continue
            seen_ids.add(record_id)
            client.delete_record(model_name, record_id)


def delete_stale_seed_media_records(
    client: PapyrusGraphQLAuthoringClient,
    records_by_model: dict[str, list[dict[str, Any]]],
) -> None:
    ordered = {
        "PublishedMediaAsset": records_by_model.get("PublishedMediaAsset", []),
        "MediaAsset": records_by_model.get("MediaAsset", []),
    }
    delete_stale_seed_records(client, ordered)


def upload_seed_media(payload: dict[str, Any], *, bucket: str) -> None:
    for article in payload["articles"]:
        for asset_index, asset in enumerate(article_image_assets(article)):
            upload_seed_image(article, asset, asset_index, bucket=bucket)
        video_asset = article_video_asset(article)
        if video_asset and should_seed_video_uploads():
            upload_seed_video(article, video_asset, bucket=bucket)
    edition_video = payload.get("video")
    if isinstance(edition_video, dict) and should_seed_video_uploads():
        upload_seed_edition_video(payload, edition_video, bucket=bucket)


def upload_seed_image(article: dict[str, Any], asset: dict[str, Any], index: int, *, bucket: str) -> None:
    metadata = seed_image_upload_metadata(article, asset, index)
    source = seed_image_source_path(asset["src"])
    content_type = metadata["contentType"]
    if source is None:
        with tempfile.NamedTemporaryFile() as tmp:
            with urllib.request.urlopen(asset["src"]) as response:
                tmp.write(response.read())
            tmp.flush()
            aws_s3_cp(tmp.name, bucket, metadata["storagePath"], content_type)
    else:
        aws_s3_cp(str(source), bucket, metadata["storagePath"], content_type)

    for variant in iter_seed_image_variants(article, asset, index):
        variant_source = seed_image_source_path(variant["src"])
        if variant_source is None:
            with tempfile.NamedTemporaryFile() as tmp:
                with urllib.request.urlopen(variant["src"]) as response:
                    tmp.write(response.read())
                tmp.flush()
                aws_s3_cp(tmp.name, bucket, variant["storagePath"], variant["contentType"])
        else:
            aws_s3_cp(str(variant_source), bucket, variant["storagePath"], variant["contentType"])


def aws_s3_cp(source_path: str, bucket: str, storage_path: str, content_type: str) -> None:
    result = subprocess.run(
        [
            "aws",
            "s3",
            "cp",
            source_path,
            f"s3://{bucket}/{storage_path}",
            "--content-type",
            content_type,
            "--cache-control",
            "public, max-age=31536000, immutable",
        ],
        cwd=PAPYRUS_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to upload seed media {storage_path}: {result.stderr or result.stdout}")


def seed_image_upload_metadata(article: dict[str, Any], asset: dict[str, Any], index: int) -> dict[str, Any]:
    content_type = content_type_for_source(asset["src"])
    extension = image_extension(content_type, asset["src"])
    layout = asset.get("layout") or {}
    preferred_height = layout.get("preferredHeight")
    aspect_ratio = layout.get("aspectRatio")
    return {
        "storagePath": f"media/articles/{article['slug']}/{index + 1:02d}-{asset['id']}.{extension}",
        "contentType": content_type,
        "width": round(aspect_ratio * preferred_height) if aspect_ratio and preferred_height else None,
        "height": preferred_height,
    }


def iter_seed_image_variants(article: dict[str, Any], asset: dict[str, Any], index: int) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    dark = nested_get(asset, "themeVariants", "dark")
    if isinstance(dark, dict) and isinstance(dark.get("src"), str) and dark["src"].strip():
        src = dark["src"].strip()
        content_type = content_type_for_source(src)
        extension = image_extension(content_type, src)
        variants.append(
            {
                "name": "dark",
                "src": src,
                "storagePath": f"media/articles/{article['slug']}/{index + 1:02d}-{asset['id']}-dark.{extension}",
                "contentType": content_type,
            }
        )
    return variants


def seed_image_theme_variants_metadata(article: dict[str, Any], asset: dict[str, Any], index: int) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for variant in iter_seed_image_variants(article, asset, index):
        entry = {"sourceUrl": variant["src"], "storagePath": variant["storagePath"]}
        metadata[variant["name"]] = entry
    return metadata


def article_image_assets(article: dict[str, Any]) -> list[dict[str, Any]]:
    assets = [asset for asset in article.get("assets") or [] if asset.get("type") == "image"]
    if assets:
        return assets
    if not isinstance(article.get("image"), dict) or not normalize_string(article["image"].get("src")):
        return []
    return [
        {
            **article["image"],
            "id": f"{article['slug']}-primary-image",
            "type": "image",
            "roles": ["lead", "continuation", "continuationInset"],
        }
    ]


def article_video_asset(article: dict[str, Any]) -> dict[str, Any] | None:
    video = article.get("video")
    if not isinstance(video, dict):
        return None
    if not normalize_string(video.get("src")):
        return None
    return video


def should_seed_video_uploads() -> bool:
    return os.environ.get("PAPYRUS_SEED_VIDEOS") == "1"


def article_video_storage_path(slug: str) -> str:
    return f"media/articles/{slug}/video-{slug}.mp4"


def article_video_light_storage_path(slug: str) -> str:
    return f"media/articles/{slug}/video-{slug}-light.mp4"


def article_video_dark_storage_path(slug: str) -> str:
    return f"media/articles/{slug}/video-{slug}-dark.mp4"


def edition_video_storage_path(edition_slug: str) -> str:
    return f"media/editions/{edition_slug}/edition-overview.mp4"


def edition_video_light_storage_path(edition_slug: str) -> str:
    return f"media/editions/{edition_slug}/edition-overview-light.mp4"


def edition_video_dark_storage_path(edition_slug: str) -> str:
    return f"media/editions/{edition_slug}/edition-overview-dark.mp4"


def seed_video_upload_metadata(article: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "storagePath": article_video_storage_path(str(article["slug"])),
        "contentType": "video/mp4",
    }


def seed_edition_video_upload_metadata(payload: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    edition_slug = str(payload.get("slug") or payload.get("id") or "edition").strip()
    return {
        "storagePath": edition_video_storage_path(edition_slug),
        "contentType": "video/mp4",
    }


def build_video_theme_variants_metadata(
    asset: dict[str, Any],
    *,
    article_slug: str | None = None,
    edition_slug: str | None = None,
) -> dict[str, Any] | None:
    theme_variants = nested_get(asset, "themeVariants")
    if not isinstance(theme_variants, dict):
        return None

    variants: dict[str, Any] = {}
    light = theme_variants.get("light")
    light_src = normalize_string(light.get("src")) if isinstance(light, dict) else None
    light_storage_path = (
        article_video_light_storage_path(article_slug)
        if article_slug
        else edition_video_light_storage_path(edition_slug or "current")
        if edition_slug
        else None
    )
    if light_src or light_storage_path:
        entry: dict[str, Any] = {}
        if light_storage_path:
            entry["storagePath"] = light_storage_path
        if light_src:
            entry["sourceUrl"] = light_src
        variants["light"] = entry

    dark = theme_variants.get("dark")
    dark_src = normalize_string(dark.get("src")) if isinstance(dark, dict) else None
    dark_storage_path = (
        article_video_dark_storage_path(article_slug)
        if article_slug
        else edition_video_dark_storage_path(edition_slug or "current")
        if edition_slug
        else None
    )
    if dark_src or dark_storage_path:
        entry = {}
        if dark_storage_path:
            entry["storagePath"] = dark_storage_path
        if dark_src:
            entry["sourceUrl"] = dark_src
        variants["dark"] = entry

    return variants or None


def build_edition_video_metadata(payload: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    edition_slug = str(payload.get("slug") or payload.get("id") or "edition").strip()
    record = dict(asset)
    record["storagePath"] = edition_video_storage_path(edition_slug)
    theme_variants = build_video_theme_variants_metadata(asset, edition_slug=edition_slug)
    if theme_variants:
        record["themeVariants"] = theme_variants
    return record


def upload_seed_video(article: dict[str, Any], asset: dict[str, Any], *, bucket: str) -> None:
    slug = str(article["slug"])
    upload_seed_video_file(bucket, asset["src"], article_video_storage_path(slug))
    light_src = normalize_string(nested_get(asset, "themeVariants", "light", "src"))
    if light_src:
        upload_seed_video_file(bucket, light_src, article_video_light_storage_path(slug))
    dark_src = normalize_string(nested_get(asset, "themeVariants", "dark", "src"))
    if dark_src:
        upload_seed_video_file(bucket, dark_src, article_video_dark_storage_path(slug))


def upload_seed_edition_video(payload: dict[str, Any], asset: dict[str, Any], *, bucket: str) -> None:
    edition_slug = str(payload.get("slug") or payload.get("id") or "edition").strip()
    upload_seed_video_file(bucket, asset["src"], edition_video_storage_path(edition_slug))
    light_src = normalize_string(nested_get(asset, "themeVariants", "light", "src"))
    if light_src:
        upload_seed_video_file(bucket, light_src, edition_video_light_storage_path(edition_slug))
    dark_src = normalize_string(nested_get(asset, "themeVariants", "dark", "src"))
    if dark_src:
        upload_seed_video_file(bucket, dark_src, edition_video_dark_storage_path(edition_slug))


def upload_seed_video_file(bucket: str, src: str, storage_path: str) -> None:
    source = seed_video_source_path(src)
    if source is not None and source.exists():
        aws_s3_cp(str(source), bucket, storage_path, "video/mp4")
        return
    if s3_object_exists(bucket, storage_path):
        print(f"seed\tvideo-skip\t{storage_path}")
        return
    raise ValueError(
        f"Seed video file not found for {storage_path}: {src}. "
        "Run `poetry run papyrus videos seed` first or upload the object to S3."
    )


def s3_object_exists(bucket: str, storage_path: str) -> bool:
    result = subprocess.run(
        ["aws", "s3api", "head-object", "--bucket", bucket, "--key", storage_path],
        cwd=PAPYRUS_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def seed_video_source_path(src: str) -> Path | None:
    if re.match(r"^https?://", src):
        return None
    path = Path(src)
    if path.is_absolute() and path.exists():
        return path
    return PAPYRUS_ROOT / (Path("public") / src.lstrip("/") if src.startswith("/") else Path(src))


def video_media_metadata(asset: dict[str, Any], *, article_slug: str | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"sourceUrl": asset.get("src")}
    poster = normalize_string(asset.get("posterSrc"))
    if poster:
        metadata["posterSrc"] = poster
    duration = asset.get("durationSeconds")
    if isinstance(duration, (int, float)):
        metadata["durationSeconds"] = duration
    theme_variants = build_video_theme_variants_metadata(asset, article_slug=article_slug)
    if theme_variants:
        metadata["themeVariants"] = theme_variants
    return metadata


def seed_image_source_path(src: str) -> Path | None:
    if re.match(r"^https?://", src):
        return None
    path = Path(src)
    if path.is_absolute() and path.exists():
        return path
    return PAPYRUS_ROOT / (Path("public") / src.lstrip("/") if src.startswith("/") else Path(src))


def content_type_for_source(src: str) -> str:
    source_path = seed_image_source_path(src)
    guess_source = str(source_path or src)
    guessed, _encoding = mimetypes.guess_type(guess_source)
    return guessed or "image/jpeg"


def image_extension(content_type: str, src: str) -> str:
    if "png" in content_type:
        return "png"
    if "svg" in content_type:
        return "svg"
    if "webp" in content_type:
        return "webp"
    if "gif" in content_type:
        return "gif"
    suffix = Path(src).suffix.lstrip(".")
    return suffix or "jpg"


def create_seed_edition_layout_plan(articles: list[dict[str, Any]]) -> dict[str, Any]:
    item_ids = [str(article["slug"]) for article in articles]
    image_by_item_id = {str(article["slug"]): article_has_image(article) for article in articles}
    front_item_ids = item_ids[: min(len(item_ids), 4)]
    follow_on_blocks = [
        *[
            seed_continuation_block(item_id, 0, seed_media_placement(0) if image_by_item_id.get(item_id) else None)
            for item_id in front_item_ids
        ],
        *[
            seed_page_article_block(
                item_id,
                0,
                seed_media_placement(index + len(front_item_ids)) if image_by_item_id.get(item_id) else None,
            )
            for index, item_id in enumerate(item_ids[len(front_item_ids) :])
        ],
    ]
    return {
        "pages": [
            {
                "id": "page-1",
                "pageNumber": 1,
                "presetId": "front.mosaic",
                "grid": {"columns": {"min": 1, "preferred": 6, "max": 6}},
                "regions": [
                    {
                        "id": "front-page-news",
                        "type": "fullPage",
                        "localGrid": {"columns": {"min": 1, "preferred": 6, "max": 6}},
                        "responsiveLayouts": seed_front_responsive_layouts(),
                        "blocks": [
                            seed_front_block(item_id, index, image_by_item_id.get(item_id, False))
                            for index, item_id in enumerate(front_item_ids)
                        ],
                    }
                ],
            },
            *seed_follow_on_pages(follow_on_blocks),
        ]
    }


def article_has_image(article: dict[str, Any]) -> bool:
    assets = article.get("assets") if isinstance(article.get("assets"), list) else []
    return any(asset.get("type") == "image" and normalize_string(asset.get("src")) for asset in assets) or bool(
        normalize_string((article.get("image") or {}).get("src") if isinstance(article.get("image"), dict) else None)
    )


def seed_front_block(item_id: str, index: int, has_image: bool) -> dict[str, Any]:
    preferred_span = [1, 4, 1, 2, 2, 2][index] if index < 6 else 1
    is_feature = index == 1
    block = {
        "id": f"front-{item_id}",
        "type": "articleFrame",
        "presetId": "front.teaser",
        "itemId": item_id,
        "flowKey": item_id,
        "startCursor": "beginning",
        "role": "feature" if is_feature else "rail" if index in {0, 2} else "standard",
        "editorialPriority": "primary" if is_feature else "secondary" if index in {0, 2} else "tertiary",
        "typography": {"headlineScale": "feature" if is_feature else "standard"},
        "span": {"min": 1, "preferred": preferred_span, "max": preferred_span},
        "media": [],
        "cutPolicy": seed_cut_policy(item_id, index),
    }
    if is_feature:
        block["localGrid"] = {"columns": {"min": 1, "preferred": 4, "max": 4}}
        block["media"] = [
            {
                "required": True,
                "assetRole": "lead",
                "placement": {
                    "anchor": "right",
                    "span": {"min": 1, "preferred": 1, "max": 1},
                    "vertical": "top",
                    "collapse": "inline",
                    "crop": "preserve",
                    "wrapsText": True,
                },
            }
        ] if has_image else []
        block["composition"] = seed_feature_composition(has_image)
    return {key: value for key, value in block.items() if value is not None}


def seed_feature_composition(has_image: bool) -> dict[str, Any]:
    left_title_span = {
        "columnStart": 1,
        "span": {"min": 1, "preferred": 3, "max": 3},
        "spanOverrides": {"3": 2},
        "vertical": "top",
        "collapse": "inline",
        "crop": "preserve",
        "wrapsText": False,
    }
    left_lead_span = {**left_title_span, "wrapsText": True}
    lead = [
        {"slot": "deck", "placement": left_lead_span},
        {"slot": "byline", "placement": left_lead_span},
    ]
    if has_image:
        lead.append(
            {
                "slot": "media",
                "mediaIndex": 0,
                "placement": {
                    "anchor": "right",
                    "span": {"min": 1, "preferred": 1, "max": 1},
                    "vertical": "top",
                    "collapse": "inline",
                    "crop": "preserve",
                    "wrapsText": True,
                },
            }
        )
    return {
        "title": [
            {
                "slot": "label",
                "placement": {
                    "columnStart": 1,
                    "span": {"min": 1, "preferred": 2, "max": 2},
                    "vertical": "top",
                    "collapse": "inline",
                    "crop": "preserve",
                    "wrapsText": False,
                },
            },
            {"slot": "headline", "placement": left_title_span},
        ],
        "lead": lead,
    }


def seed_region_stack_page(page_number: int, region_specs: list[tuple]) -> dict[str, Any]:
    return {
        "id": f"page-{page_number}",
        "pageNumber": page_number,
        "presetId": "page.regionStack",
        "grid": {"columns": {"min": 1, "preferred": 6, "max": 6}},
        "regions": [
            {
                "id": region_id,
                "type": "stack",
                "role": role,
                "size": {"ratio": 0.5},
                "blocks": [
                    (
                        seed_page_article_block(item_id, page_number, media_spec(anchor, min_span, preferred_span, max_span, vertical, required))
                        if block_kind == "page"
                        else seed_continuation_block(item_id, page_number, media_spec(anchor, min_span, preferred_span, max_span, vertical, required))
                    )
                ],
            }
            for (
                region_id,
                role,
                item_id,
                block_kind,
                anchor,
                min_span,
                preferred_span,
                max_span,
                vertical,
                required,
            ) in region_specs
        ],
    }


def seed_follow_on_pages(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for page_index, page_blocks in enumerate(chunk(blocks, 2)):
        page_number = page_index + 2
        pages.append(
            {
                "id": f"page-{page_number}",
                "pageNumber": page_number,
                "presetId": "page.regionStack",
                "grid": {"columns": {"min": 1, "preferred": 6, "max": 6}},
                "regions": [
                    {
                        "id": f"{block['itemId']}-page-{page_number}-{'top' if block_index == 0 else 'bottom'}",
                        "type": "stack",
                        "role": "top" if block_index == 0 else "bottom",
                        "size": {"ratio": 1 if len(page_blocks) == 1 else 0.5},
                        "blocks": [
                            {
                                **block,
                                "id": f"{block['id']}-page-{page_number}",
                                **({} if block.get("startCursor") == "current" else {"startCursor": "beginning"}),
                            }
                        ],
                    }
                    for block_index, block in enumerate(page_blocks)
                ],
            }
        )
    return pages


def chunk(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def seed_media_placement(index: int) -> dict[str, Any]:
    if index % 2 == 0:
        return media_spec("right", 1, 2, 2, "top", False)
    return media_spec("center", 1, 2, 3, "upperThird", False)


def media_spec(anchor: str, min_span: int, preferred: int, max_span: int, vertical: str, required: bool) -> dict[str, Any]:
    return {
        "required": required,
        "anchor": anchor,
        "span": {"min": min_span, "preferred": preferred, "max": max_span},
        "vertical": vertical,
    }


def seed_page_article_block(item_id: str, page_number: int, media: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "id": f"{item_id}-page-{page_number}-lead",
        "type": "articleFrame",
        "presetId": "article.mediaInset",
        "itemId": item_id,
        "flowKey": item_id,
        "startCursor": "beginning",
        "role": "primary",
        "localGrid": {"columns": {"min": 2, "preferred": 6, "max": 6}},
        "media": [article_media_placement("lead", media)] if media else [],
    }


def seed_continuation_block(item_id: str, page_number: int, media: dict[str, Any] | None) -> dict[str, Any]:
    block = {
        "id": f"{item_id}-page-{page_number}",
        "type": "articleFrame",
        "presetId": "article.mediaInset",
        "itemId": item_id,
        "flowKey": item_id,
        "startCursor": "current",
        "role": "primary",
        "localGrid": {"columns": {"min": 2, "preferred": 6, "max": 6}},
        "media": [article_media_placement("continuationInset", media)] if media else [],
        "pullQuote": {
            "required": False,
            "placements": [
                {
                    "anchor": "right" if media["anchor"] == "left" else "left",
                    "span": {"min": 1, "preferred": 1, "max": 2},
                    "vertical": "middle",
                    "collapse": "omit",
                    "crop": "preserve",
                    "wrapsText": True,
                }
            ],
        } if media else None,
    }
    return {key: value for key, value in block.items() if value is not None}


def article_media_placement(asset_role: str, media: dict[str, Any]) -> dict[str, Any]:
    return {
        "required": media["required"],
        "assetRole": asset_role,
        "placement": {
            "anchor": media["anchor"],
            "span": media["span"],
            "vertical": media["vertical"],
            "collapse": "inline",
            "crop": "preserve",
            "wrapsText": True,
        },
    }


def seed_front_responsive_layouts() -> list[dict[str, Any]]:
    return [
        {
            "minColumns": 6,
            "maxColumns": 6,
            "order": "editorialPriority",
            "slots": [
                priority_slot("secondary", 1, 1, 1, 1, 1),
                priority_slot("primary", 1, 2, 4, 1, 1),
                priority_slot("secondary", 2, 6, 1, 1, 1),
            ],
            "overflow": {"columnSpan": "full", "rowSpan": 1},
        },
        {
            "minColumns": 5,
            "maxColumns": 5,
            "order": "editorialPriority",
            "slots": [
                priority_slot("secondary", 1, 1, 1, 1, 1),
                priority_slot("primary", 1, 2, 3, 1, 1),
                priority_slot("secondary", 2, 5, 1, 1, 1),
            ],
            "overflow": {"columnSpan": "full", "rowSpan": 1},
        },
        {
            "minColumns": 4,
            "maxColumns": 4,
            "order": "editorialPriority",
            "slots": [
                priority_slot("primary", 1, 1, 4, 1, 1),
                priority_slot("secondary", 1, 1, 2, 2, 1),
                priority_slot("secondary", 2, 3, 2, 2, 1),
            ],
            "overflow": {"columnSpan": "full", "rowSpan": 1},
        },
        {
            "minColumns": 1,
            "maxColumns": 3,
            "order": "editorialPriority",
            "slots": [],
            "overflow": {"columnSpan": "full", "rowSpan": 1},
        },
    ]


def priority_slot(priority: str, occurrence: int, column_start: int, column_span: int, row_start: int, row_span: int) -> dict[str, Any]:
    return {
        "editorialPriority": priority,
        "priorityOccurrence": occurrence,
        "columnStart": column_start,
        "columnSpan": column_span,
        "rowStart": row_start,
        "rowSpan": row_span,
    }


def seed_cut_policy(_item_id: str, index: int) -> dict[str, Any] | None:
    if index > 3:
        return None
    return {
        "bodyDepthRows": 8 if index == 3 else 14,
        "jumpTargetPage": index // 2 + 2,
    }


def order_articles(source: list[dict[str, Any]], article_order: list[str]) -> list[dict[str, Any]]:
    order = {slug: index for index, slug in enumerate(article_order)}
    return sorted(source, key=lambda article: (order.get(article["slug"], 10**9), article["slug"]))


def record(model_name: str, expected: dict[str, Any]) -> dict[str, Any]:
    return {"modelName": model_name, "expected": compact_dict(expected)}


def compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {key: entry for key, entry in value.items() if entry is not None}


def with_version_fields(
    source: dict[str, Any],
    *,
    lineage_id: str,
    version_created_at: str,
    version_created_by: str,
    change_reason: str,
) -> dict[str, Any]:
    versioned = {
        **source,
        "lineageId": lineage_id,
        "versionNumber": 1,
        "previousVersionId": None,
        "versionState": "current",
        "versionCreatedAt": version_created_at,
        "versionCreatedBy": version_created_by,
        "changeReason": change_reason,
    }
    return {**versioned, "contentHash": content_hash_for(versioned)}


def content_hash_for(value: Any) -> str:
    return "sha256:" + hashlib.sha256(stable_stringify(value).encode("utf-8")).hexdigest()


def stable_stringify(value: Any) -> str:
    if value is None or not isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(stable_stringify(entry) for entry in value) + "]"
    entries = [(key, entry) for key, entry in value.items() if entry is not None]
    return "{" + ",".join(f"{json.dumps(key, separators=(',', ':'))}:{stable_stringify(entry)}" for key, entry in sorted(entries)) + "}"


def to_aws_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def slugify(value: str) -> str:
    return re.sub(r"(^-+|-+$)", "", re.sub(r"[^a-z0-9]+", "-", value.lower()))


def published_edition_id(edition_id: str) -> str:
    return f"published-{edition_id}"


def published_item_id(item_id: str) -> str:
    return f"published-{item_id}"


def media_metadata(asset: dict[str, Any], theme_variants: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = {"sourceUrl": asset.get("src")}
    inline_float = nested_get(asset, "layout", "inlineFloat")
    if inline_float:
        metadata["inlineFloat"] = inline_float
    if theme_variants:
        metadata["themeVariants"] = theme_variants
    return metadata


def nested_get(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def summarize_changes(changes: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"create": 0, "update": 0, "noop": 0}
    for change in changes:
        action = change.get("action") or "noop"
        counts[action] = counts.get(action, 0) + 1
    return counts


def print_seed_summary(result: dict[str, Any]) -> None:
    print(f"seed-edition\tedition\t{result['editionId']}")
    print(f"seed-edition\tarticles\t{result['articleCount']}")
    print(f"seed-edition\trecords\t{result['recordCount']}")
    print(f"seed-edition\tcreate\t{result['changes'].get('create', 0)}")
    print(f"seed-edition\tupdate\t{result['changes'].get('update', 0)}")
    print(f"seed-edition\tnoop\t{result['changes'].get('noop', 0)}")
    print(f"seed-edition\tapply\t{'yes' if result['apply'] else 'no'}")
