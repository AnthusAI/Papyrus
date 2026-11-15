"""Front end tokens through the real checker and generator."""
import copy

from behave import given, when, then

from papyrus_content.front_end_tokens import TOKENS, build_tokens_css, lint_stylesheet, lint_tokens


@given('the shipped design tokens')
def step_shipped_tokens(context):
    context.tokens = copy.deepcopy(TOKENS)


@given('the shipped design tokens with the body text set to 16 pixels on wide screens')
def step_small_body(context):
    context.tokens = copy.deepcopy(TOKENS)
    context.tokens['text']['body']['wide']['size'] = 16


@given('the shipped design tokens with the caption line height set to 18 pixels on wide screens')
def step_off_rhythm(context):
    context.tokens = copy.deepcopy(TOKENS)
    context.tokens['text']['caption']['wide']['line'] = 18


@given('a stylesheet that sets a heading to 12px')
def step_literal_size(context):
    context.stylesheet = 'h2 { font-size: 12px; }'


@when('the tokens are checked against the size policy')
def step_check_tokens(context):
    context.problems = lint_tokens(context.tokens)


@when('the stylesheet is checked against the size policy')
def step_check_stylesheet(context):
    context.problems = lint_stylesheet(context.stylesheet)


@when('the token stylesheet is generated')
def step_generate(context):
    context.css = build_tokens_css(context.tokens)


@then('no problem is reported')
def step_no_problem(context):
    assert context.problems == [], context.problems


@then('the check names text.body.wide as 16px below the reading floor of 18px')
def step_names_body(context):
    assert any('text.body.wide: 16px is below the reading floor of 18px' in problem for problem in context.problems), context.problems


@then('the check says the caption line height is not a whole number of rhythm steps')
def step_names_caption(context):
    assert any('text.caption.wide' in problem and 'not a whole number' in problem for problem in context.problems), context.problems


@then('the check says the size is not a token')
def step_not_token(context):
    assert len(context.problems) == 1 and 'not a token' in context.problems[0], context.problems


@then('compact values are the defaults, and the wide block lists only tokens whose value changes')
def step_wide_overrides(context):
    defaults, wide = context.css.split('@media (min-width: 600px)')
    assert '--papyrus-text-caption-size: 0.875rem' in defaults
    assert '--papyrus-text-caption-size' not in wide and '--papyrus-text-display-size: 3.5rem' in wide
