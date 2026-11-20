from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_FEATURES_ROOT = REPOSITORY_ROOT / "features_backend"
READING_GUIDE_PATH = BACKEND_FEATURES_ROOT / "README.md"
DIRECTORIES_THAT_ARE_NOT_PRODUCT_AREAS = {"steps", "fixtures", "__pycache__"}
LOWER_CASE_HYPHENATED_FEATURE_FILE_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*\.feature$")


def product_area_directory_names() -> set[str]:
    return {
        entry.name
        for entry in BACKEND_FEATURES_ROOT.iterdir()
        if entry.is_dir() and entry.name not in DIRECTORIES_THAT_ARE_NOT_PRODUCT_AREAS
    }


def relative_link_targets_in_the_reading_guide() -> list[str]:
    return re.findall(r"\]\(([^)#]+)\)", READING_GUIDE_PATH.read_text(encoding="utf-8"))


def test_no_feature_file_sits_outside_a_product_area() -> None:
    feature_files_at_the_top_level = sorted(path.name for path in BACKEND_FEATURES_ROOT.glob("*.feature"))
    assert feature_files_at_the_top_level == [], (
        "Move these into the product area that features_backend/README.md describes: "
        + ", ".join(feature_files_at_the_top_level)
    )


def test_no_product_area_has_directories_of_its_own() -> None:
    feature_files_nested_inside_an_area = sorted(
        str(path.relative_to(BACKEND_FEATURES_ROOT))
        for area_name in product_area_directory_names()
        for path in (BACKEND_FEATURES_ROOT / area_name).rglob("*.feature")
        if path.parent.name != area_name
    )
    assert feature_files_nested_inside_an_area == []


def test_every_feature_file_name_is_lower_case_with_hyphens() -> None:
    badly_named_feature_files = sorted(
        str(path.relative_to(BACKEND_FEATURES_ROOT))
        for area_name in product_area_directory_names()
        for path in (BACKEND_FEATURES_ROOT / area_name).glob("*.feature")
        if not LOWER_CASE_HYPHENATED_FEATURE_FILE_NAME.match(path.name)
    )
    assert badly_named_feature_files == []


def test_the_reading_guide_describes_every_product_area() -> None:
    areas_linked_from_the_reading_guide = {
        target.rstrip("/") for target in relative_link_targets_in_the_reading_guide() if target.endswith("/")
    }
    assert areas_linked_from_the_reading_guide == product_area_directory_names()


def test_every_feature_the_reading_guide_recommends_exists() -> None:
    recommended_features_that_are_missing = sorted(
        target
        for target in relative_link_targets_in_the_reading_guide()
        if target.endswith(".feature") and not (BACKEND_FEATURES_ROOT / target).is_file()
    )
    assert recommended_features_that_are_missing == []


def test_every_product_area_holds_at_least_one_feature() -> None:
    empty_product_areas = sorted(
        area_name
        for area_name in product_area_directory_names()
        if not any((BACKEND_FEATURES_ROOT / area_name).glob("*.feature"))
    )
    assert empty_product_areas == []
