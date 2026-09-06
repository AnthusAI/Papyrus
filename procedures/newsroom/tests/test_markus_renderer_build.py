from __future__ import annotations

from pathlib import Path

from papyrus_content.markus_renderer.build import _build_nav_items, _discover_articles


def test_build_nav_items_lists_home_and_all_articles(tmp_path: Path) -> None:
    articles_dir = tmp_path / "articles"
    articles_dir.mkdir()
    (articles_dir / "alpha.md").write_text("---\ntitle: Alpha\n---\n\nOne.", encoding="utf-8")
    (articles_dir / "beta.md").write_text("---\ntitle: Beta\n---\n\nTwo.", encoding="utf-8")

    articles = _discover_articles(tmp_path)
    nav_items = _build_nav_items(articles)

    assert [item.label for item in nav_items] == [
        "Home",
        "Alpha",
        "Beta",
    ]
    assert [item.href for item in nav_items] == [
        "index.html",
        "articles/alpha.html",
        "articles/beta.html",
    ]
