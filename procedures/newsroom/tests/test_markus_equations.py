"""Equations in Stories (PPY-e1de14): TeX in the source, safe MathML in the page."""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from papyrus_content.email_render.render import _body as email_body
from papyrus_content.email_render.theme import EmailTheme
from papyrus_content.markus_renderer.build import render_fragment_text
from papyrus_content.markus_renderer.convert import convert_text_in_process
from papyrus_content.markus_renderer.derive import derive_body
from papyrus_content.markus_renderer.equations import (
    EquationError,
    find_equations,
    render_equations,
    tex_to_mathml,
)

REAL_EQUATIONS = [
    r"\Pr[\text{guess}] \le m / 2^k",
    r"\sum_{i=1}^{n} x_i",
    r"\frac{a}{b}",
    r"H_\infty(X) = -\log_2 \max_x \Pr[X = x]",
    r"\begin{aligned} a &= b + c \\ d &= e \end{aligned}",
    r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}",
    r"\sqrt{x^2+1} \ge \left( \frac{1}{2} \right)^{n}",
]


def page(markdown: str, **options) -> str:
    return render_fragment_text(markdown, convert=convert_text_in_process, **options)


class ConversionTests(unittest.TestCase):
    def test_real_equations_become_wellformed_mathml(self) -> None:
        for tex in REAL_EQUATIONS:
            with self.subTest(tex=tex):
                math = tex_to_mathml(tex, display=True)
                root = ET.fromstring(math)
                self.assertTrue(root.tag.endswith("}math"))
                self.assertEqual(root.attrib["display"], "block")
                self.assertNotIn("<mi>&</mi>", math)

    def test_the_bound_from_the_issue(self) -> None:
        math = tex_to_mathml(r"\Pr[\text{guess}] \le m / 2^k", display=False)
        self.assertIn("<mtext>guess</mtext>", math)
        self.assertIn("<msup><mn>2</mn><mi>k</mi></msup>", math)
        self.assertIn("≤", math)
        self.assertIn('display="inline"', math)

    def test_aligned_has_two_rows_and_no_equation_numbers(self) -> None:
        math = tex_to_mathml(r"\begin{aligned} a &= b \\ c &= d \end{aligned}", display=True)
        self.assertEqual(math.count("<mtr>"), 2)
        self.assertNotIn("(1)", math)

    def test_alt_text_carries_the_source(self) -> None:
        self.assertIn('alttext="\\frac{a}{b}"', tex_to_mathml(r"\frac{a}{b}", display=True))

    def test_bad_tex_raises(self) -> None:
        for tex in (r"\frac{", r"x^", r"\left( x", "", "   ", r"\notacommand{x}", r"a &= b"):
            with self.subTest(tex=tex), self.assertRaises(EquationError):
                tex_to_mathml(tex, display=True)


class SpacingAndFontTests(unittest.TestCase):
    def test_named_operators_get_no_left_space_and_a_thin_right_space(self) -> None:
        math = tex_to_mathml(r"\Pr[X = x] \le m / 2^k", display=True)
        self.assertIn('<mo movablelimits="true" lspace="0em" rspace="0.1667em">Pr</mo>', math)

    def test_function_names_get_a_thin_space_after_them(self) -> None:
        math = tex_to_mathml(r"-\log_2 \max_x \Pr[X = x]", display=True)
        self.assertIn('<msub><mi>log</mi><mn>2</mn></msub><mspace width="0.1667em"></mspace>', math)
        ET.fromstring(math)

    def test_signs_and_brackets_keep_their_default_spacing(self) -> None:
        math = tex_to_mathml(r"a \le b", display=False)
        self.assertNotIn("lspace", math)

    def test_stylesheet_asks_for_system_math_fonts_and_ships_none(self) -> None:
        from papyrus_content.projection.standard.projector import ASSET_DIRECTORY

        css = (ASSET_DIRECTORY / "markus-components.css").read_text(encoding="utf-8")
        rule = next(line for line in css.splitlines() if line.startswith("math {"))
        families = [name.strip().strip('"') for name in rule.split("font-family:")[1].split(";")[0].split(",")]
        self.assertEqual(families[0], "STIX Two Math")
        self.assertEqual(families[-1], "math")  # the generic family is the last resort, not the first choice
        self.assertNotIn("@font-face", css)
        self.assertNotIn(".woff", css)
        self.assertNotIn("border", rule)


class InjectionTests(unittest.TestCase):
    ATTACKS = [
        r"\text{</mtext><script>alert(1)</script><mtext>}",
        r"\text{<img src=x onerror=alert(1)>}",
        r"\href{javascript:alert(1)}{x}",
        r"\style{background:url(javascript:alert(1))}{x}",
        r"\color{red}{x}",
        r"\text{</mtext></mrow></math><script>alert(1)</script>}",
        '\\text{" onmouseover="alert(1)}',
        r"<script>alert(1)</script>",
    ]

    def test_attacks_never_reach_the_converter_output(self) -> None:
        for tex in self.ATTACKS:
            with self.subTest(tex=tex):
                try:
                    math = tex_to_mathml(tex, display=True)
                except EquationError:
                    continue
                self.assertNotIn("<script", math)
                self.assertNotIn("<img", math)
                self.assertNotIn("javascript:", math)
                self.assertNotIn("onerror=", math.replace("&", ""))
                for element in ET.fromstring(math).iter():
                    self.assertTrue(element.tag.rsplit("}", 1)[-1].startswith("m"), element.tag)
                    self.assertFalse({"href", "style", "onmouseover"} & set(element.attrib))

    def test_angle_brackets_in_math_are_escaped_text(self) -> None:
        math = tex_to_mathml(r"a < b", display=False)
        self.assertNotIn("<b", math.replace("<mi>b", ""))
        ET.fromstring(math)

    def test_full_page_with_script_in_tex_has_no_live_script(self) -> None:
        out = page("```math\n\\text{</mtext><script>alert(1)</script><mtext>}\n```\n\nIn text $`\\text{<img src=x onerror=1>}`$.\n")
        self.assertNotIn("<script", out)
        self.assertNotIn("<img", out)
        self.assertIn("&lt;script&gt;alert(1)", out)  # the author's text is still visible, as code


class PageTests(unittest.TestCase):
    def test_display_fence_becomes_a_math_block(self) -> None:
        out = page("Before.\n\n```math\n\\frac{a}{b}\n```\n\nAfter.\n")
        self.assertIn('<div class="papyrus-math"><math xmlns="http://www.w3.org/1998/Math/MathML" display="block"', out)
        self.assertNotIn("language-math", out)

    def test_inline_form_becomes_inline_math(self) -> None:
        out = page("An attacker wins with chance at most $`m / 2^k`$ here.\n")
        self.assertIn('display="inline"', out)
        self.assertNotIn("<code>", out)
        self.assertNotIn("$", out)

    def test_dollar_prices_are_not_math(self) -> None:
        text = "It costs $5 or $6, not $10 `to` $20.\n"
        out = page(text)
        self.assertNotIn("<math", out)
        self.assertIn("$5 or $6, not $10 <code>to</code> $20.", out)

    def test_plain_code_with_dollars_is_untouched(self) -> None:
        out = page("Run `$HOME/bin` and ``$`x`$`` literally.\n")
        self.assertNotIn("<math", out)

    def test_tex_punctuation_survives_the_code_span(self) -> None:
        out = page(r"Chance $`\Pr[X_i = x_j] \le *a* \{0,1\}^n`$ holds." + "\n")
        self.assertEqual(out.count("<math"), 1)
        self.assertNotIn("<em>", out)

    def test_bad_display_tex_keeps_source_visible_as_code(self) -> None:
        out = page("```math\n\\left( a < b\n```\n")
        self.assertNotIn("<math", out)
        self.assertIn('<pre><code class="language-math">\\left( a &lt; b', out)

    def test_bad_inline_tex_keeps_source_visible(self) -> None:
        out = page("See $`\\frac{`$ here.\n")
        self.assertNotIn("<math", out)
        self.assertIn("$<code>\\frac{</code>$", out)

    def test_other_code_fences_are_untouched(self) -> None:
        text = "```python\nx = 1\n```\n"
        self.assertEqual(page(text), convert_text_in_process(text))

    def test_page_without_math_is_byte_identical(self) -> None:
        text = "# T\n\nPlain text with `code` and $5.\n"
        self.assertEqual(page(text), convert_text_in_process(text))

    def test_render_equations_is_idempotent(self) -> None:
        once = page("A $`x^2`$.\n\n```math\ny\n```\n")
        self.assertEqual(render_equations(once), once)


class SourceModeTests(unittest.TestCase):
    def test_source_mode_keeps_tex_as_code(self) -> None:
        out = page("Chance $`m / 2^k`$.\n\n```math\n\\frac{a}{b}\n```\n", equations="source")
        self.assertNotIn("<math", out)
        self.assertIn("<code>m / 2^k</code>", out)
        self.assertIn('<pre><code class="language-math">\\frac{a}{b}', out)

    def test_email_shows_the_source_in_code_styling(self) -> None:
        html, plain = email_body("Chance $`m / 2^k`$.\n\n```math\n\\frac{a}{b}\n```\n", EmailTheme(accent="#b3261e", text="#222222", background="#f1ece4"), "https://example.org")
        self.assertNotIn("<math", html)
        self.assertIn("m / 2^k", html)
        self.assertIn("\\frac{a}{b}", html)
        self.assertIn("m / 2^k", plain)
        self.assertIn("\\frac{a}{b}", plain)
        self.assertRegex(html, r"<(code|pre)\b")


class DeriveTests(unittest.TestCase):
    def derive(self, body: str):
        return derive_body("", body)

    def test_valid_equations_make_no_warning(self) -> None:
        result = self.derive("Inline $`x^2`$.\n\n```math\n\\frac{a}{b}\n```\n")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.warnings, ())

    def test_bad_equation_warns_but_still_saves(self) -> None:
        result = self.derive("Intro.\n\n```math\n\\frac{\n```\n\nInline $`x^`$.\n")
        self.assertTrue(result.ok)
        self.assertEqual([w.code for w in result.warnings], ["equation-tex", "equation-tex"])
        self.assertEqual(result.warnings[0].line, 3)
        self.assertIn("Display equation", result.warnings[0].message)
        self.assertIn("Inline equation", result.warnings[1].message)

    def test_dollar_prices_never_warn(self) -> None:
        self.assertEqual(self.derive("It costs $5 and $6 and `$x`.\n").warnings, ())

    def test_math_in_a_list_and_a_quote_is_found(self) -> None:
        document = self.derive("- item $`\\frac{`$\n\n> quote $`y^`$\n").body_ir["document"]
        self.assertEqual(len(find_equations(document)), 2)

    def test_stored_ir_keeps_the_tex_source(self) -> None:
        document = self.derive("```math\n\\frac{a}{b}\n```\n").body_ir["document"]
        self.assertEqual(document["children"][0]["value"], "\\frac{a}{b}\n")


if __name__ == "__main__":
    unittest.main()
