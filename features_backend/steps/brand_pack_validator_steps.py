"""BrandPack validation through the real validator, using the shared vectors file as the source of example packs."""
import copy
import json
from pathlib import Path

from behave import given, when, then

from papyrus_content.brand_pack import validate_brand_pack

VECTORS_PATH = Path(__file__).resolve().parents[2] / 'scripts' / 'fixtures' / 'brand-pack-vectors.json'


def _vectors():
    return json.loads(VECTORS_PATH.read_text(encoding='utf-8'))['cases']


def _valid_pack():
    return copy.deepcopy(next(case['pack'] for case in _vectors() if case['name'] == 'valid in both themes'))


@given('a brand pack for Lantern Quay with its own colours and fonts from the allow-list')
def step_valid_pack(context):
    context.brand_pack = _valid_pack()


@given('a brand pack whose body text is too faint in dark mode')
def step_faint_dark_text(context):
    context.brand_pack = _valid_pack()
    context.brand_pack['colors']['dark']['ink'] = '#5A6672'


@given('a brand pack whose dark-mode rule colour has the same lightness as the page')
def step_hue_only_rule(context):
    context.brand_pack = _valid_pack()
    context.brand_pack['colors']['dark']['rule'] = '#2A1F3D'


@given('a brand pack that asks for the heading font Comic Sans MS')
def step_bad_font(context):
    context.brand_pack = _valid_pack()
    context.brand_pack['fonts']['heading'] = 'Comic Sans MS'


@given('a brand pack that carries custom CSS')
def step_custom_css(context):
    context.brand_pack = _valid_pack()
    context.brand_pack['css'] = 'body { background: red; }'


@given('a brand pack with a setting the format does not have')
def step_unknown_setting(context):
    context.brand_pack = _valid_pack()
    context.brand_pack['sparkle'] = True


@given('the shared brand pack vectors')
def step_vectors(context):
    context.vectors = _vectors()


@when('the brand pack is validated')
def step_validate(context):
    context.brand_pack_errors = validate_brand_pack(context.brand_pack)


@when('every vector is validated')
def step_validate_vectors(context):
    context.vector_results = [(case, validate_brand_pack(case['pack'])) for case in context.vectors]


@then('the brand pack is accepted in light and in dark')
def step_accepted(context):
    assert context.brand_pack_errors == [], context.brand_pack_errors
    assert set(context.brand_pack['colors']) == {'light', 'dark'}


@then('it is refused naming ink on bg in the dark theme with its measured contrast ratio')
def step_refused_pair(context):
    matching = [e for e in context.brand_pack_errors if e.startswith('colors.dark: ink on bg ') and 'has contrast 3.06:1, needs 4.5:1' in e]
    assert matching, context.brand_pack_errors


@then('it is refused naming rule on bg in the dark theme as needing a lightness difference')
def step_refused_lightness(context):
    matching = [e for e in context.brand_pack_errors if e.startswith('colors.dark: rule on bg ') and 'must differ in lightness, not only hue' in e and '1.16:1' in e]
    assert matching, context.brand_pack_errors


@then('it is refused naming the heading font and listing the allowed fonts')
def step_refused_font(context):
    assert len(context.brand_pack_errors) == 1, context.brand_pack_errors
    message = context.brand_pack_errors[0]
    assert message.startswith("fonts.heading: 'Comic Sans MS' is not an allowed font") and 'Playfair Display' in message, message


@then('it is refused naming the css setting as not allowed on the shared tier')
def step_refused_css(context):
    assert context.brand_pack_errors == ['css: refused on the shared tier, custom CSS is not allowed; brand changes go through the brand pack'], context.brand_pack_errors


@then('it is refused naming the unknown setting')
def step_refused_unknown(context):
    assert context.brand_pack_errors == ['sparkle: is not a BrandPack setting'], context.brand_pack_errors


@then('each vector gets its expected result')
def step_vector_results(context):
    assert context.vector_results
    for case, errors in context.vector_results:
        assert len(errors) == len(case['errors']), (case['name'], errors)
        for expected in case['errors']:
            assert any(expected in error for error in errors), (case['name'], expected, errors)
