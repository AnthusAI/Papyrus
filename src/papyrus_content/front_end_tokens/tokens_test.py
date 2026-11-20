"""The standard front end's tokens: final sizes, floors enforced, one generated stylesheet that is never stale."""

from __future__ import annotations

import copy

from papyrus_content.front_end_tokens import TOKENS, build_tokens_css, lint_stylesheet, lint_tokens
from papyrus_content.front_end_tokens.build import STYLESHEET_PATH


def test_the_shipped_tokens_pass_the_size_policy():
    assert lint_tokens() == []


def test_the_generated_stylesheet_is_current():
    assert STYLESHEET_PATH.read_text(encoding="utf-8") == build_tokens_css()


def test_the_wide_layout_overrides_only_what_differs():
    css = build_tokens_css()
    wide = css.split("@media (min-width: 600px)")[1]
    assert "--papyrus-text-display-size: 3.5rem" in wide
    assert "--papyrus-text-caption-size" not in wide  # the same size in both layouts is written once


def test_there_is_no_multiplier_and_no_root_size():
    css = build_tokens_css()
    assert "html" not in css and "calc(" not in css.replace("calc(16 / 9)", "")


def test_a_text_size_below_its_floor_is_refused_in_either_layout():
    for layout in ("compact", "wide"):
        tokens = copy.deepcopy(TOKENS)
        tokens["text"]["body"][layout]["size"] = 16
        problems = lint_tokens(tokens)
        assert any(f"text.body.{layout}: 16px is below the reading floor of 18px" in problem for problem in problems), problems


def test_a_line_height_off_the_rhythm_or_too_tight_is_refused():
    tokens = copy.deepcopy(TOKENS)
    tokens["text"]["caption"]["wide"]["line"] = 18
    problems = lint_tokens(tokens)
    assert any("not a whole number" in problem for problem in problems)
    tokens["text"]["caption"]["wide"]["line"] = 16
    assert any("is under 1.3 times" in problem for problem in lint_tokens(tokens))


def test_a_stylesheet_may_use_size_tokens_but_not_literal_text_sizes():
    assert lint_stylesheet(".a { font-size: var(--papyrus-text-body-size); } .b { font-size: inherit; } .c { font-size: 0.9em; }") == []
    problems = lint_stylesheet(".a { font-size: 12px; } .b { font: 600 .8rem/1.2 serif; } /* font-size: 9px */")
    assert len(problems) == 2 and "12px" in problems[0] and ".8rem" in problems[1]


def test_the_core_token_stylesheet_passes_its_own_lint():
    assert lint_stylesheet(STYLESHEET_PATH.read_text(encoding="utf-8")) == []


def test_the_shared_publication_theme_uses_only_tokens_for_text_sizes():
    theme = STYLESHEET_PATH.with_name("papyrus-publication.css")
    assert lint_stylesheet(theme.read_text(encoding="utf-8")) == []
