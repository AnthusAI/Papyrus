from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_FEATURES_ROOT = REPOSITORY_ROOT / "features_backend"
READING_GUIDE_PATH = BACKEND_FEATURES_ROOT / "README.md"
DIRECTORIES_THAT_ARE_NOT_PRODUCT_AREAS = {"steps", "fixtures", "__pycache__"}
LOWER_CASE_HYPHENATED_FEATURE_FILE_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*\.feature$")
TICKET_ID_OR_SLICE_NUMBER = re.compile(r"PPY-[0-9a-f]{6}|\bslice [A-Z]\d")
LINE_THAT_ENDS_A_FEATURE_DESCRIPTION = re.compile(r"\s*(@|#|Scenario|Background|Rule|Example)")
FEWEST_WORDS_IN_A_FEATURE_TITLE = 4
FEWEST_WORDS_IN_A_FEATURE_DESCRIPTION = 20


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


def title_and_description_of_every_feature() -> dict[str, tuple[str, str]]:
    title_and_description_by_feature = {}
    for area_name in product_area_directory_names():
        for path in (BACKEND_FEATURES_ROOT / area_name).glob("*.feature"):
            lines = path.read_text(encoding="utf-8").split("\n")
            title_line_number = next(number for number, line in enumerate(lines) if line.startswith("Feature:"))
            description_lines = []
            for line in lines[title_line_number + 1 :]:
                if LINE_THAT_ENDS_A_FEATURE_DESCRIPTION.match(line):
                    break
                description_lines.append(line.strip())
            title_and_description_by_feature[str(path.relative_to(BACKEND_FEATURES_ROOT))] = (
                lines[title_line_number][len("Feature:") :].strip(),
                " ".join(description_lines),
            )
    return title_and_description_by_feature


def test_every_feature_title_is_a_sentence_and_not_a_bare_topic() -> None:
    features_titled_with_a_bare_topic = sorted(
        f"{feature}: {title}"
        for feature, (title, _) in title_and_description_of_every_feature().items()
        if len(title.split()) < FEWEST_WORDS_IN_A_FEATURE_TITLE
    )
    assert features_titled_with_a_bare_topic == [], "Say what Papyrus does, as features_backend/README.md asks"


def test_no_feature_cites_a_ticket_id_or_slice_number() -> None:
    features_that_cite_a_ticket = sorted(
        str(feature_path.relative_to(BACKEND_FEATURES_ROOT))
        for feature_path in BACKEND_FEATURES_ROOT.rglob("*.feature")
        if TICKET_ID_OR_SLICE_NUMBER.search(feature_path.read_text(encoding="utf-8"))
    )
    assert features_that_cite_a_ticket == [], "Describe what is true now; tickets belong on the board"


def test_every_feature_opens_by_saying_what_the_behaviour_is_for() -> None:
    features_with_a_thin_description = sorted(
        feature
        for feature, (_, description) in title_and_description_of_every_feature().items()
        if len(description.split()) < FEWEST_WORDS_IN_A_FEATURE_DESCRIPTION
    )
    assert features_with_a_thin_description == []
