"""The words in a figure's SVG source: found, and replaced without touching anything else."""
from __future__ import annotations

from papyrus_content.figures.text import has_embedded_text, replace_segments, text_segments

SVG = """<svg viewBox="0 0 680 160"><title>Hazard</title><desc>Not drawn.</desc>
<!--primitives-->
<rect fill="{ground}"/>
<text x="1" y="2" class="t-label" fill="{ink}">Hazard</text>
<text x="1" y="40" class="t-label"><tspan x="1">Safeguard 1</tspan><tspan x="1" dy="32">R&amp;D</tspan></text>
<text class="t-numeral">3</text>
</svg>"""


def test_the_words_are_the_text_elements_and_not_the_title_or_description():
    assert text_segments(SVG) == ["Hazard", "Safeguard 1", "R&D", "3"]
    assert has_embedded_text(SVG) and not has_embedded_text("<svg><rect/></svg>")


def test_replacing_keeps_every_other_character():
    out = replace_segments(SVG, {"Hazard": "Peligro", "Safeguard 1": "Defensa 1", "R&D": "I+D & más"})
    assert "<title>Hazard</title>" in out and "<!--primitives-->" in out and 'fill="{ink}">Peligro</text>' in out
    assert "<tspan x=\"1\">Defensa 1</tspan><tspan x=\"1\" dy=\"32\">I+D &amp; más</tspan>" in out
    assert '<text class="t-numeral">3</text>' in out
    assert out.replace("Peligro", "Hazard").replace("Defensa 1", "Safeguard 1").replace("I+D &amp; más", "R&amp;D") == SVG
