"""Equations in Stories: TeX in the source, MathML in the built page (PPY-e1de14).

Authoring syntax (specified in ``docs/markus-content-markup.md``):

* display: a fenced block whose info string is ``math``
* inline: a code span with a dollar sign on each side, ``$`m / 2^k`$`` (the GitHub spelling)

Both are plain Markdown that Markus already understands, so Markus is not involved: the fence arrives as
``<pre><code class="language-math">`` (the way Mermaid does) and the inline form as ``$<code>...</code>$``.
After Markus has converted a page, :func:`render_equations` swaps each of them for MathML generated here.
The code span matters: TeX is full of ``_``, ``*``, ``\\`` and braces that Markdown would otherwise read, and a code span
leaves them alone. A bare ``$`` is never math -- stored articles contain prices.

Safety
------
``latex2mathml`` does not escape what authors type: ``\\text{</mtext><script>...}`` becomes a real ``<script>`` element and
``\\href`` / ``\\style`` become attributes. So its output is never trusted. It is parsed, checked against a whitelist of
MathML elements and attributes, and written out again by :func:`_serialize` with every text and value escaped. An
equation that fails any step is left exactly as the author wrote it (the source stays visible as code) and is reported.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML"

_DISPLAY_RE = re.compile(r'<pre><code class="language-math">(?P<tex>.*?)</code></pre>', re.S)
_INLINE_RE = re.compile(r"\$<code>(?P<tex>[^<]+)</code>\$")

ALLOWED_ELEMENTS = frozenset(
    "math mrow mi mn mo ms mtext mspace msup msub msubsup munder mover munderover mfrac msqrt mroot "
    "mtable mtr mtd mstyle mpadded mphantom menclose merror".split()
)
ALLOWED_ATTRIBUTES = frozenset(
    "display mathvariant stretchy fence form movablelimits accent accentunder displaystyle scriptlevel "
    "rowspacing columnspacing columnalign rowalign linebreak lspace rspace width height depth separator symmetric "
    "largeop minsize maxsize notation linethickness".split()
)
_SAFE_VALUE = re.compile(r"^[\w\s.%+-]*$")
_ENVIRONMENT_ALIASES = ((re.compile(r"\\(begin|end)\{aligned\}"), r"\\\1{align*}"),)


class EquationError(ValueError):
    """The TeX could not be turned into safe MathML; the message says why."""


@dataclass(frozen=True)
class Equation:
    tex: str
    display: bool
    line: int | None = None


def _mathml(tex: str, display: bool) -> str:
    import latex2mathml.converter

    for pattern, replacement in _ENVIRONMENT_ALIASES:
        tex = pattern.sub(replacement, tex)
    try:
        return latex2mathml.converter.convert(tex, display="block" if display else "inline")
    except Exception as exc:  # the converter raises a family of exceptions with empty messages
        reason = type(exc).__name__.removesuffix("Error")
        raise EquationError(f"TeX not understood ({reason or 'syntax'})") from exc


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _check(element: ET.Element) -> None:
    tag = _local(element.tag)
    if tag not in ALLOWED_ELEMENTS:
        raise EquationError(f"unsupported element <{tag}>")
    for name, value in element.attrib.items():
        if _local(name) not in ALLOWED_ATTRIBUTES or not _SAFE_VALUE.match(value):
            raise EquationError(f"unsupported attribute {_local(name)!r}")
    text = element.text or ""
    if tag in ("mi", "mo", "mn") and ("\\" in text or text == "&"):
        # An unknown command comes out as text beginning with a backslash; a stray alignment mark as "&".
        raise EquationError(f"unknown command or stray alignment mark {text!r}")
    for child in element:
        _check(child)


_SCRIPTS = ("msub", "msup", "msubsup", "munder", "mover", "munderover")


def _script_operators(element: ET.Element) -> dict[str, set[int]]:
    """The ``<mo>`` elements (by ``id``) that are the base of a script element, and those inside a script (every child after the base)."""
    bases: set[int] = set()
    inside: set[int] = set()
    for node in element.iter():
        if _local(node.tag) in _SCRIPTS and len(node):
            if _local(node[0].tag) == "mo":
                bases.add(id(node[0]))
            for script in list(node)[1:]:
                inside.update(id(inner) for inner in script.iter() if _local(inner.tag) == "mo")
    return {"bases": bases, "inside": inside}


def _tidy(element: ET.Element) -> None:
    """Spacing for named operators (``Pr``, ``max``, ``lim``...).

    latex2mathml writes them as ``<mo>``; an ``<mo>`` between other things gets the wide spacing of an infix sign such as
    ``=``, so ``\\Pr[X]`` came out as ``Pr   [X]``. A named operator wants no space before it and a thin space after it.
    """
    scripted = _script_operators(element)
    for node in element.iter():
        text = node.text or ""
        if _local(node.tag) == "mo" and len(text) > 1 and text.isalpha() and "lspace" not in node.attrib and id(node) not in scripted["bases"]:
            node.set("lspace", "0em")
            node.set("rspace", "0.1667em")
    # WebKit puts an operator's own lspace/rspace between a script's base and its script (``\\max_x`` came out as ``max x``,
    # ``H_\\infty`` as ``H ∞``), and around the signs inside a script. Chromium and Firefox ignore it there. So an operator
    # that is the base of a script, or inside one, carries no spacing of its own; the thin space after a base comes from an <mspace> below.
    for node in element.iter():
        if _local(node.tag) == "mo" and (id(node) in scripted["bases"] or id(node) in scripted["inside"]):
            node.set("lspace", "0em")
            node.set("rspace", "0em")
    # Function names written as <mi> (``\\log``, ``\\sin``), alone or as the base of a subscript, need the same thin space
    # after them, or ``\\log_2 \\max_x`` runs together.
    for parent in list(element.iter()):
        if _local(parent.tag) not in ("math", "mrow", "mtd", "mstyle"):
            continue  # inside a script or a fraction the children are positional; a gap would change the structure
        children = list(parent)
        for position, child in reversed(list(enumerate(children))):  # last first, so earlier positions stay valid
            name = child
            if _local(child.tag) in ("msub", "msup", "msubsup") and len(child):
                name = child[0]
            text = name.text or ""
            if _local(name.tag) in ("mi", "mo") and len(text) > 1 and text.isalpha() and position + 1 < len(children):
                gap = ET.Element("mspace", {"width": "0.1667em"})
                parent.insert(position + 1, gap)


def _serialize(element: ET.Element, alttext: str | None = None) -> str:
    tag = _local(element.tag)
    attributes = {_local(name): value for name, value in element.attrib.items()}
    if tag == "math":
        attributes = {"xmlns": MATHML_NAMESPACE, **attributes}
        if alttext is not None:
            attributes["alttext"] = alttext
    rendered = "".join(f' {name}="{html.escape(value, quote=True)}"' for name, value in attributes.items())
    body = html.escape(element.text or "", quote=False)
    for child in element:
        body += _serialize(child) + html.escape(child.tail or "", quote=False)
    return f"<{tag}{rendered}>{body}</{tag}>"


def tex_to_mathml(tex: str, *, display: bool) -> str:
    """MathML for ``tex``, safe to put in a page. Raises :class:`EquationError` for anything else."""
    source = tex.strip()
    if not source:
        raise EquationError("empty equation")
    converted = _mathml(source, display)
    try:
        root = ET.fromstring(converted)
    except ET.ParseError as exc:
        raise EquationError("the TeX produced markup that is not well formed (a stray < or &)") from exc
    _check(root)
    _tidy(root)
    return _serialize(root, alttext=" ".join(source.split()))


def _unescape_code(text: str) -> str:
    return html.unescape(text)


def render_equations(fragment: str, *, mode: str = "mathml") -> str:
    """Replace each equation in a converted fragment.

    ``mode="mathml"`` writes MathML; an equation that cannot be converted keeps its source as code.
    ``mode="source"`` (email: Gmail ignores MathML) keeps every equation as its TeX source in code styling.
    """
    if "language-math" not in fragment and "$<code>" not in fragment:
        return fragment

    def display(match: re.Match[str]) -> str:
        if mode == "source":
            return match.group(0)
        try:
            math = tex_to_mathml(_unescape_code(match.group("tex")), display=True)
        except EquationError:
            return match.group(0)
        return f'<div class="papyrus-math">{math}</div>'

    def inline(match: re.Match[str]) -> str:
        if mode == "source":
            return f"<code>{match.group('tex')}</code>"
        try:
            return tex_to_mathml(_unescape_code(match.group("tex")), display=False)
        except EquationError:
            return match.group(0)

    return _INLINE_RE.sub(inline, _DISPLAY_RE.sub(display, fragment))


def find_equations(document: dict) -> list[Equation]:
    """Every equation in a Markus document dict (``Document.to_dict()``), in reading order."""
    found: list[Equation] = []

    def visit_inlines(nodes: list[dict], line: int | None) -> None:
        for index, node in enumerate(nodes):
            if node.get("type") == "code_span":
                before = nodes[index - 1] if index else None
                after = nodes[index + 1] if index + 1 < len(nodes) else None
                if (
                    before and before.get("type") == "text" and before.get("text", "").endswith("$")
                    and after and after.get("type") == "text" and after.get("text", "").startswith("$")
                ):
                    found.append(Equation(node.get("code", ""), False, line))
            for key in ("children", "inline"):
                if isinstance(node.get(key), list):
                    visit_inlines(node[key], line)

    def visit(node: dict) -> None:
        line = node.get("line")
        if node.get("type") == "code" and node.get("lang") == "math":
            found.append(Equation(node.get("value", ""), True, line))
        if isinstance(node.get("inline"), list):
            visit_inlines(node["inline"], line)
        for key in ("children", "header", "rows", "items"):
            value = node.get(key)
            if isinstance(value, list):
                for child in value:
                    if isinstance(child, dict):
                        visit(child)
                    elif isinstance(child, list):
                        for cell in child:
                            if isinstance(cell, dict) and "type" in cell:
                                visit(cell)
                            elif isinstance(cell, list):
                                visit_inlines(cell, line)

    visit(document)
    return found


def equation_problems(document: dict) -> list[tuple[Equation, str]]:
    """The equations in ``document`` that would not render, each with the reason."""
    problems = []
    for equation in find_equations(document):
        try:
            tex_to_mathml(equation.tex, display=equation.display)
        except EquationError as exc:
            problems.append((equation, str(exc)))
    return problems
