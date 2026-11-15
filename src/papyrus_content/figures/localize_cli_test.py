"""``papyrus figures localize``: the words are translated, the folder for the language is written and rendered, and nothing is saved without --save."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from papyrus_content.figures.figures_test import METADATA, SOURCE
from papyrus_content.figures.localize_cli import figures_localize, write_language_folder
from papyrus_content.figures.renderer import RendererUnavailable, open_browser

WORDS = {"labels": {"Hello": "Hola"}, "alt": "Un cuadro", "caption": "Un cuadro.", "findings": [], "costUsd": 0.0, "language": "es-419"}


def figure(tmp_path: Path) -> Path:
    folder = tmp_path / "plain"
    folder.mkdir()
    (folder / "figure.svg").write_text(SOURCE, encoding="utf-8")
    (folder / "figure.json").write_text(json.dumps(METADATA), encoding="utf-8")
    return folder


def test_the_language_folder_holds_the_translated_words_and_names_its_original(tmp_path):
    written = write_language_folder(figure(tmp_path), "es-419", WORDS, tmp_path)
    assert written.name == "plain-es-419"
    assert ">Hola</text>" in (written / "figure.svg").read_text(encoding="utf-8") and ">One tile</title>" in (written / "figure.svg").read_text(encoding="utf-8")
    metadata = json.loads((written / "figure.json").read_text(encoding="utf-8"))
    assert (metadata["slug"], metadata["localizedFrom"], metadata["language"], metadata["alt"], metadata["caption"]) == ("plain-es-419", "plain", "es-419", "Un cuadro", "Un cuadro.")


def test_a_figure_with_no_text_has_nothing_to_localize(tmp_path, capsys):
    folder = figure(tmp_path)
    (folder / "figure.svg").write_text(SOURCE.replace(">Hello<", "><"), encoding="utf-8")
    assert figures_localize([str(folder), "--story", "s", "--language", "es-419", "--neutral-default"]) == 0
    assert "nothing to localize" in capsys.readouterr().out


def test_localize_renders_the_language_figure_and_saves_only_when_asked(tmp_path, capsys):
    try:
        with open_browser():
            pass
    except RendererUnavailable:
        pytest.skip("no Chromium or Chrome here")
    folder = figure(tmp_path)
    saved = []
    with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(object(), None)), \
            mock.patch("papyrus_content.localize.figure_labels.translate_figure_words", return_value=WORDS), \
            mock.patch("papyrus_content.figures.localize_cli._original_path", return_value="assets/s/plain.png"), \
            mock.patch("papyrus_content.story_commands._version_author", return_value="Ed"), \
            mock.patch("papyrus_content.localize.image_save.save_variant", side_effect=lambda *a, **k: saved.append(k) or ["figures\tvariant\tsaved\tv"]):
        assert figures_localize([str(folder), "--story", "s", "--language", "es-419", "--neutral-default"]) == 0
        assert not saved and "figures variant --story s --language es-419 --original assets/s/plain.png" in capsys.readouterr().out
        assert (tmp_path / "pictures" / "plain-es-419.png").is_file() and (tmp_path / "pictures" / "plain-es-419.dark.png").is_file()
        assert figures_localize([str(folder), "--story", "s", "--language", "es-419", "--neutral-default", "--save", "--reason", "Spanish labels", "--author-label", "Ed"]) == 0
    assert len(saved) == 1 and saved[0]["original"] == "assets/s/plain.png" and saved[0]["texts"] == {"alt": "Un cuadro", "caption": "Un cuadro."}
