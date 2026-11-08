"""The deterministic checks of the four lenses (docs/four-lens-review.md; PPY-59c772).

Pure over one Story's text and, when it is known, the site's settings: no network, no model, no writes, and nothing read from the rest of the site.
The preview the checks judge is the one the projector emits (``projection/standard/share_preview.py``), and the Markdown copy is built with the
projector's own function, so a check never judges a stand-in.

Every check ends in exactly one state (``audience_lenses.STATES``). ``not_assessable`` is never a pass: it says what Papyrus could not tell and why.
Where a check would want a length or a count, it reports the value and does not compare it to a number Papyrus invented.

Not built here: the model-judged checks (Jev, Luna), the checks that need the rest of the site (duplicate titles, links in), the editorial check
(P11), the fact check (P13), the picture file (C4) and the checks after publishing. ``NOT_RUN`` names them with the reason."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from . import audience_lenses as lenses
from .audience_lenses import CONCERN, ERROR, NOT_APPLICABLE, NOT_ASSESSABLE, PASS, PROBLEM
from .markus_renderer.content_markup import _IMAGE_DIRECTIVE_RE, parse_attrs
from .markus_renderer.derive import compose_source
from .projection.public_data import SUMMARY_FIELD_NAMES
from .projection.source import summary_from_row
from .projection.standard import blocks
from .projection.standard.config import StandardSettings, standard_settings_from_mapping
from .projection.standard.entries import entry_for_summary
from .projection.standard.environment import SiteEnvironment, resolve_environment
from .projection.standard.head import HeadBuilder
from .projection.standard.markdown import body_of, item_markdown
from .projection.standard.share_preview import SharePreview, item_share_preview
from .projection.standard.urls import UrlPolicy
from .projection.stored import parse_front_matter

SETTINGS_FILE = "projection.json"

#: Plain words for what could not be checked, shown with the finding (docs/four-lens-review.md).
NO_SETTINGS = "Papyrus cannot read this site's settings here, so this was not checked. Run from the site's checkout, or pass --static with the web directory that holds projection.json."
NO_ORIGIN = "Papyrus cannot build the page's web address yet, because the site has no public address. Share and search tags cannot be checked."
NOT_LIVE = "This site is not open to search or to AI readers yet (it asks them to stay away). We checked what we could on the draft."

#: What this module does not run, and why, by check key.
NOT_RUN = {
    "P3": "needs the decision model", "P4": "needs the decision model", "P5": "needs the decision model", "P9": "needs a picture-reading model and a person",
    "P11": "runs through the editorial check", "P12": "a person decides", "P13": "needs the fact check, which is not built for drafts", "P14": "a person decides",
    "P15": "needs this site's own history of Stories", "A6": "needs the decision model", "A7": "needs the decision model", "A12": "after publishing",
    "A14": "a person decides", "S3": "needs the decision model", "S8": "needs the rest of the site", "S9": "needs the decision model",
    "S10": "needs the decision model", "S11": "needs the decision model", "S12": "after publishing", "S13": "Papyrus has no view of what search engines have indexed",
    "S14": "a person decides", "C4": "needs the picture file", "C8": "needs the decision model", "C9": "needs the decision model",
    "C10": "needs the decision model", "C11": "drawn in the final review", "C12": "after publishing", "C13": "a person decides",
}


@dataclass(frozen=True)
class LensStory:
    """One version of one Story: what the checks read."""

    lineage: str
    version_id: str
    version_number: int
    stage: str
    title: str
    body: str
    front_matter_yaml: str
    row: Mapping[str, Any]


@dataclass(frozen=True)
class LensSite:
    standard: StandardSettings
    environment: SiteEnvironment


def story_from_row(row: Mapping[str, Any]) -> LensStory:
    metadata = row.get("metadata")
    if isinstance(metadata, str):
        metadata = json.loads(metadata) if metadata.strip() else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    return LensStory(
        lineage=str(row.get("lineageId") or row.get("id") or ""), version_id=str(row.get("id") or ""), version_number=int(row.get("versionNumber") or 1),
        stage=str(row.get("stage") or ""), title=str(row.get("headline") or row.get("title") or ""), body=str(row.get("bodyMarkus") or ""),
        front_matter_yaml=str(metadata.get("frontMatterYaml") or ""), row=row,
    )


def load_site(static_directory: Path | str | None, environ: Mapping[str, str] | None = None) -> LensSite | None:
    """The site's settings from the ``projection.json`` in its web directory, or None when there is none."""
    if not static_directory:
        return None
    path = Path(static_directory) / SETTINGS_FILE
    if not path.is_file():
        return None
    standard = standard_settings_from_mapping(json.loads(path.read_text(encoding="utf-8")))
    return LensSite(standard, resolve_environment(standard, environ))


# --- reading the text -------------------------------------------------------------------------------------------------------------

FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$")
MARKDOWN_IMAGE = re.compile(r'!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)(?:\s+"(?P<title>[^"]*)")?\)')
MARKDOWN_LINK = re.compile(r"(?<!!)\[(?P<text>[^\]]+)\]\((?P<href>[^)\s]+)[^)]*\)")
CITATION = re.compile(r"\[@(?P<keys>[^\]\n]+)\]")
IMAGE_FILE = re.compile(r"\.(png|jpe?g|gif|webp|svg|avif)$", re.I)
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
#: Link texts and alt texts that say nothing out of context.
WEAK_LINK_TEXTS = frozenset({"here", "click here", "this", "this link", "link", "read more", "more", "learn more", "this page", "see here", "source"})
PLACEHOLDER_ALT = frozenset({"image", "picture", "photo", "img", "graphic", "figure", "screenshot", "alt", "alt text"})
PLACEHOLDER_TITLES = re.compile(r"^(untitled|new story|draft|todo|tbd|headline|title|placeholder|lorem ipsum)\b", re.I)
EMPTY_HEADINGS = frozenset({"introduction", "conclusion", "overview", "summary", "intro"})
OPENING_LENGTH = 200   # the projector's own lede length (fragments.lede_of): the opening is read the way the projector reads it


def mask_fences(text: str) -> str:
    """The text with the lines of fenced code blocks emptied, so line numbers stay and code is not read as prose."""
    out, fence = [], None
    for line in text.split("\n"):
        marker = FENCE.match(line)
        if marker is not None:
            ticks = marker.group(1)
            if fence is None:
                fence = ticks
            elif ticks[0] == fence[0] and len(ticks) >= len(fence) and not line.strip()[len(ticks):].strip():
                fence = None
            out.append("")
        else:
            out.append("" if fence is not None else line)
    return "\n".join(out)


@dataclass(frozen=True)
class Image:
    line: int
    src: str
    alt: str | None        # None: the text never says (a missing alt); "": said to be empty (a deliberate decoration, for a directive)
    caption: str
    credit: str
    directive: bool

    @property
    def remote(self) -> bool:
        return self.src.startswith(("http://", "https://"))


def images_of(masked_body: str) -> list[Image]:
    found: list[Image] = []
    for match in _IMAGE_DIRECTIVE_RE.finditer(masked_body):
        attributes = parse_attrs(match.group("attrs"))
        found.append(Image(masked_body.count("\n", 0, match.start()) + 1, attributes.get("src", ""), attributes.get("alt"), attributes.get("caption", ""),
                           attributes.get("credit", ""), True))
    for match in MARKDOWN_IMAGE.finditer(masked_body):
        alt = match.group("alt").strip()
        found.append(Image(masked_body.count("\n", 0, match.start()) + 1, match.group("src"), alt or None, match.group("title") or "", "", False))
    return sorted(found, key=lambda image: image.line)


def headings_of(masked_body: str) -> list[tuple[int, int, str]]:
    return [(number, len(match.group(1)), match.group(2).strip()) for number, line in enumerate(masked_body.split("\n"), start=1) if (match := HEADING.match(line))]


def plain(text: str) -> str:
    text = MARKDOWN_IMAGE.sub(" ", text)
    text = MARKDOWN_LINK.sub(lambda match: match.group("text"), text)
    text = CITATION.sub(" ", text)
    text = re.sub(r"[*_`]+", "", text)
    return " ".join(text.split())


def paragraphs_of(masked_body: str) -> list[tuple[int, str, str]]:
    """Prose paragraphs as (line, plain text, text as written): not headings, directives, lists, quotes or tables."""
    out, current, start = [], [], 0
    for number, line in enumerate(masked_body.split("\n") + [""], start=1):
        if line.strip():
            if not current:
                start = number
            current.append(line)
            continue
        if current:
            first = current[0].lstrip()
            if not first.startswith(("#", "::", ":::", "|", ">", "- ", "* ", "+ ", "<")) and not re.match(r"\d+[.)]\s", first):
                text = plain(" ".join(current))
                if text:
                    out.append((start, text, " ".join(current)))
            current = []
    return out


def opening_of(masked_body: str) -> str:
    """The first paragraph's text, clipped as the projector clips its lede."""
    paragraphs = paragraphs_of(masked_body)
    if not paragraphs:
        return ""
    text = paragraphs[0][1]
    return text if len(text) <= OPENING_LENGTH else text[: OPENING_LENGTH - 1].rstrip() + "…"


def many(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def short(text: str, limit: int = 120) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# --- the facts every check reads ----------------------------------------------------------------------------------------------------

class Facts:
    """Everything derived from the Story once, so no check recomputes it."""

    def __init__(self, story: LensStory, site: LensSite | None) -> None:
        self.story, self.site = story, site
        self.known = site is not None
        self.standard = site.standard if site else standard_settings_from_mapping({"site": {"name": "This site"}})
        self.environment = site.environment if site else SiteEnvironment(production=True, origin=None)
        self.policy = UrlPolicy(self.standard)
        self.front_matter = parse_front_matter(story.front_matter_yaml)
        self.masked = mask_fences(story.body)
        row = dict(story.row)
        row.setdefault("slug", re.sub(r"[^a-z0-9]+", "-", (story.title or "story").lower()).strip("-") or "story")
        try:
            self.summary = summary_from_row(row)
        except ValueError:
            self.summary = None
        self.entry = None
        if self.summary is not None:
            try:
                self.entry = entry_for_summary(self.summary, self.standard, self.policy)
            except ValueError:
                pass
        self.images = images_of(self.masked)
        self.headings = headings_of(self.masked)
        self.opening = opening_of(self.masked)
        body_image = next((image.src for image in self.images if image.src), None)
        self.preview: SharePreview | None = None
        if self.entry is not None:
            self.preview = item_share_preview(self.entry, self.standard, self.policy, opening=self.opening, body_image=body_image)
        self.head = HeadBuilder(self.standard, self.environment)
        self.source_text = compose_source(story.front_matter_yaml, story.body)
        self._head_html: str | None = None

    @property
    def head_html(self) -> str:
        if self._head_html is None:
            self._head_html = self.head.build(self.preview.head) if self.preview is not None else ""
        return self._head_html


def meta(head_html: str, name: str) -> str | None:
    found = re.search(r'<meta (?:property|name)="%s" content="([^"]*)"' % re.escape(name), head_html)
    return found.group(1) if found else None


def json_ld_of(head_html: str) -> list[dict]:
    out = []
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', head_html, re.S):
        try:
            out.append(json.loads(raw.replace("<\\/", "</")))
        except ValueError:
            out.append({"@invalid": raw[:80]})
    return out


# --- findings --------------------------------------------------------------------------------------------------------------------------

def _lens_of(key: str) -> lenses.Lens:
    return next(lens for lens in lenses.LENSES if any(check.key == key for check in lens.checks))


def finding(key: str, state: str, message: str, **evidence: Any) -> dict[str, Any]:
    check = lenses.CHECK_BY_KEY[key]
    lens = _lens_of(key)
    if state == CONCERN and check.severity == ERROR:
        state = PROBLEM
    return {"check": key, "lens": lens.key, "step": lens.step, "title": check.title, "state": state, "severity": check.severity, "method": check.method,
            "message": message, "evidence": evidence, "mirrors": list(check.mirrors)}


def _unknown_site(key: str) -> dict[str, Any]:
    return finding(key, NOT_ASSESSABLE, NO_SETTINGS)


def _no_origin(key: str) -> dict[str, Any]:
    return finding(key, NOT_ASSESSABLE, NO_ORIGIN)


# --- people ----------------------------------------------------------------------------------------------------------------------------

def check_p1(facts: Facts) -> dict[str, Any]:
    title = facts.entry.title if facts.entry else facts.story.title
    named = bool(facts.front_matter.get("title") or facts.story.title)
    not_checked = ["whether another Story on this site has the same headline (Papyrus has no index of titles)"]
    if not named:
        return finding("P1", CONCERN, "The Story has no headline of its own; the page would show its address as the title.", title=title, notChecked=not_checked)
    if PLACEHOLDER_TITLES.match(title.strip()):
        return finding("P1", CONCERN, f"The headline looks like a placeholder: \"{short(title)}\".", title=title, notChecked=not_checked)
    return finding("P1", PASS, f"The headline is \"{short(title)}\".", title=title, notChecked=not_checked)


def check_p2(facts: Facts) -> dict[str, Any]:
    names = (facts.standard.summary_fields or SUMMARY_FIELD_NAMES)
    used = next((name for name in names if str(facts.front_matter.get(name) or "").strip()), None)
    if used:
        return finding("P2", PASS, f"The dek comes from \"{used}\".", field=used, text=short(str(facts.front_matter[used]), 300))
    return finding("P2", CONCERN, "The Story has no dek. The page will use its first paragraph as the description.", field=None, opening=short(facts.opening))


def _outline_issues(facts: Facts) -> tuple[list[str], list[dict]]:
    outline = [{"line": line, "level": level, "text": text} for line, level, text in facts.headings]
    issues = []
    levels = [row["level"] for row in outline]
    if levels.count(1) > 1:
        issues.append(f"The Story has {levels.count(1)} top-level headings; a page has one.")
    for before, after in zip(outline, outline[1:]):
        if after["level"] > before["level"] + 1:
            issues.append(f"The heading \"{short(after['text'], 60)}\" (line {after['line']}) skips from level {before['level']} to level {after['level']}.")
    for row in outline:
        if row["text"].strip(" :").lower() in EMPTY_HEADINGS:
            issues.append(f"The heading \"{row['text']}\" (line {row['line']}) says nothing about the section.")
    return issues, outline


def check_p6(facts: Facts) -> list[dict[str, Any]]:
    issues, outline = _outline_issues(facts)
    if not outline:
        results = [finding(key, PASS, "The Story has no headings.", outline=outline) for key in ("P6", "A9")]
    elif issues:
        results = [finding(key, CONCERN, " ".join(issues), outline=outline, issues=issues) for key in ("P6", "A9")]
    else:
        results = [finding(key, PASS, f"The {many(len(outline), 'heading')} are in order.", outline=outline) for key in ("P6", "A9")]
    return results


def _alt_state(image: Image) -> str:
    if image.alt is None:
        return "missing"
    if image.alt.strip():
        return "present"
    return "decoration" if image.directive else "missing"


def check_p7(facts: Facts) -> list[dict[str, Any]]:
    if not facts.images:
        return [finding(key, NOT_APPLICABLE, "The Story has no images.") for key in ("P7", "A10")]
    rows = [{"line": image.line, "src": image.src, "alt": _alt_state(image), "text": short(image.alt or "")} for image in facts.images]
    missing = [row for row in rows if row["alt"] == "missing"]
    p7 = (finding("P7", CONCERN, f"{len(missing)} of {len(rows)} images have no alt text: " + "; ".join(f"line {row['line']} ({short(row['src'], 60)})" for row in missing) + ".",
                  images=rows) if missing else
          finding("P7", PASS, f"All {len(rows)} images have alt text or are marked as decoration.", images=rows))
    no_equivalent = [row for row, image in zip(rows, facts.images) if row["alt"] == "missing" and not image.caption.strip()]
    a10 = (finding("A10", CONCERN, f"{many(len(no_equivalent), 'image')} with no text in the Markdown copy (no alt text and no caption): "
                   + "; ".join(f"line {row['line']}" for row in no_equivalent) + ".", images=no_equivalent) if no_equivalent else
           finding("A10", PASS, "Every image that is not decoration has text in the Markdown copy.", images=rows))
    return [p7, a10]


def check_p8(facts: Facts) -> dict[str, Any]:
    if not facts.images:
        return finding("P8", NOT_APPLICABLE, "The Story has no images.")
    bad = []
    for image in facts.images:
        alt = (image.alt or "").strip()
        if not alt:
            continue
        stem = Path(image.src.split("?")[0]).stem.lower()
        if alt.lower() in PLACEHOLDER_ALT or IMAGE_FILE.search(alt) or (stem and alt.lower() == stem) or re.fullmatch(r"(image|img|photo|picture)[-_ ]?\d+", alt.lower()):
            bad.append({"line": image.line, "alt": alt, "reason": "a filename or a generic word"})
        elif image.caption and alt.strip().lower() == image.caption.strip().lower():
            bad.append({"line": image.line, "alt": alt, "reason": "a copy of the caption"})
    if bad:
        return finding("P8", CONCERN, "Alt text that says nothing: " + "; ".join(f"line {row['line']} \"{short(row['alt'], 40)}\" ({row['reason']})" for row in bad) + ".", images=bad)
    return finding("P8", PASS, "No alt text is a filename, a generic word or a copy of the caption.")


def _cover_record(facts: Facts) -> dict:
    record = facts.front_matter.get("coverImage")
    return record if isinstance(record, dict) else {}


def check_p10(facts: Facts) -> list[dict[str, Any]]:
    record = _cover_record(facts)
    cover_src = str(record.get("srcPath") or "").lstrip("/")
    seeded = facts.front_matter.get("seededImage")
    seeded_url = str(seeded.get("url") or "") if isinstance(seeded, dict) else ""
    cover_image = str(facts.front_matter.get("image") or "").lstrip("/")
    rows, unknown = [], []
    for image in facts.images:
        src = image.src.lstrip("/")
        third = image.remote or (cover_src and src == cover_src) or (seeded_url and image.src == seeded_url)
        origin = "a remote address" if image.remote else "the stock cover record" if cover_src and src == cover_src else "a Reference's picture" if third else "unknown"
        row = {"line": image.line, "src": image.src, "thirdParty": bool(third), "origin": origin, "credit": image.credit.strip() or None}
        rows.append(row)
        if not third and not image.credit.strip():
            unknown.append(row)
    if cover_src and cover_image and not any(image.src.lstrip("/") == cover_src for image in facts.images):
        rows.append({"line": None, "src": "/" + cover_src, "thirdParty": True, "origin": "the stock cover record (front matter only)", "credit": None})
    uncredited = [row for row in rows if row["thirdParty"] and not row["credit"]]
    if not rows:
        results = [finding(key, NOT_APPLICABLE, "The Story has no pictures, so there is no credit to check.") for key in ("P10", "C6")]
    elif uncredited:
        message = f"{many(len(uncredited), 'third-party picture')} with no credit: " + "; ".join(f"{short(row['src'], 60)}" + (f" (line {row['line']})" if row["line"] else "") for row in uncredited) + "."
        results = [finding(key, CONCERN, message, images=rows) for key in ("P10", "C6")]
    elif unknown:
        results = [finding(key, NOT_ASSESSABLE, "Papyrus cannot tell where this picture came from. Add where it came from, or say it is ours.", images=rows) for key in ("P10", "C6")]
    else:
        results = [finding(key, PASS, "Every third-party picture is credited.", images=rows) for key in ("P10", "C6")]
    return results


# --- AI reader agents ----------------------------------------------------------------------------------------------------------------

def _twin(facts: Facts) -> tuple[str, str, str, list[dict]]:
    """(the Markdown copy, the body it holds, the body it should hold, what it leaves out). Built with the projector's own functions."""
    values = dict(facts.standard.values)
    source = blocks.substitute(facts.source_text, values, facts.summary.output_path)
    twin_source = blocks.twin(facts.source_text, values, facts.summary.output_path)
    canonical = facts.entry.canonical or facts.head.absolute(facts.entry.url)
    text = item_markdown(facts.entry, twin_source, canonical, (), facts.environment.origin)
    body = body_of(source)
    omitted = blocks.twin_omissions(body)
    left_out = {line for row in omitted for line in range(row["line"], row["line"] + row["lines"])}
    kept = [line for number, line in enumerate(body.split("\n"), start=1) if number not in left_out]
    expected = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return text, body_of(twin_source), expected, omitted


def check_agents(facts: Facts) -> list[dict[str, Any]]:
    keys = ("A1", "A2", "A3", "A4")
    if facts.entry is None:
        return [finding(key, NOT_ASSESSABLE, "The Story's page could not be worked out, so its Markdown copy could not be built.") for key in keys]
    results: list[dict[str, Any]] = []
    if facts.known and not facts.standard.agents.markdown:
        return [finding(key, NOT_APPLICABLE, "This site does not publish Markdown copies, so AI readers get only the web page.", agentsMarkdown=False) for key in keys]
    if not facts.known:
        results.append(_unknown_site("A1"))
    elif facts.entry.noindex:
        results.append(finding("A1", CONCERN, "The Story is marked noindex or draft, so no Markdown copy is published for it.", noindex=True))
    else:
        from .projection.standard.markdown import md_path

        path = md_path(facts.entry.key) if facts.entry.key else None
        results.append(finding("A1", PASS, f"A Markdown copy will be published at {path}.", path=path, agentsMarkdown=True))
    try:
        text, held, expected, omitted = _twin(facts)
    except ValueError as error:
        reason = f"The Markdown copy could not be built: {short(str(error), 160)}"
        return results + [finding(key, NOT_ASSESSABLE, reason) for key in ("A2", "A3", "A4")]
    body = held
    if text.endswith(body + "\n") and re.sub(r"\n{3,}", "\n\n", body).strip() == expected:
        results.append(finding("A2", PASS, "The Markdown copy is the Story's source, every directive intact.", sourceHash=digest(expected), copyHash=digest(body)))
    else:
        lines_a, lines_b = expected.split("\n"), body.split("\n")
        first = next((index for index in range(max(len(lines_a), len(lines_b))) if (lines_a[index] if index < len(lines_a) else None) != (lines_b[index] if index < len(lines_b) else None)), 0)
        results.append(finding("A2", CONCERN, f"The Markdown copy differs from the Story's source, first at line {first + 1}.", sourceHash=digest(expected), copyHash=digest(body),
                               line=first + 1, source=short(lines_a[first] if first < len(lines_a) else ""), copy=short(lines_b[first] if first < len(lines_b) else "")))
    results.append(_a3(facts, omitted))
    results.append(_a4(facts, text))
    return results


def _a3(facts: Facts, omitted: list[dict]) -> dict[str, Any]:
    islands = []
    for number, line in enumerate(mask_fences(body_of(facts.source_text)).split("\n"), start=1):
        match = re.match(r"^[ \t]*::island\{(?P<attrs>.*)\}[ \t]*$", line)
        if match and not parse_attrs(match.group("attrs")).get("summary", "").strip():
            islands.append({"kind": "island without a summary", "line": number, "lines": 1, "text": line.strip()})
    dropped = [*omitted, *islands]
    if not dropped:
        return finding("A3", PASS, "The Markdown copy leaves nothing out.")
    return finding("A3", CONCERN, f"{many(len(dropped), 'block')} with no text in the Markdown copy: " + "; ".join(f"{row['kind']} at line {row['line']}" for row in dropped) + ".", dropped=dropped)


def _a4(facts: Facts, text: str) -> dict[str, Any]:
    entry = facts.entry
    body = body_of(text)
    header = text[: len(text) - len(body) - 1].strip().split("\n") if body and text.endswith(body + "\n") else []
    missing = []
    if not entry.title:
        missing.append("title")
    if not entry.summary_text:
        missing.append("summary")
    if not entry.authors:
        missing.append("byline")
    if not entry.date:
        missing.append("published date")
    canonical = entry.canonical or facts.head.absolute(entry.url)
    if not canonical:
        missing.append("canonical address")
    if missing:
        return finding("A4", CONCERN, "The Markdown copy has no " + ", no ".join(missing) + ".", missing=missing, header=header)
    return finding("A4", PASS, "The Markdown copy carries the title, summary, byline, dates and canonical address.", header=header)


def check_a5(facts: Facts) -> dict[str, Any]:
    from .fact_check import name_runs, numbers_in, quotations

    cited: list[str] = []
    for match in CITATION.finditer(facts.masked):
        cited += [key.strip().lstrip("@") for key in re.split(r"[;,]", match.group("keys")) if key.strip()]
    known = facts.front_matter.get("citations")
    known_keys = set(known) if isinstance(known, dict) else set()
    unresolved = sorted({key for key in cited if key not in known_keys})
    listed = bool(re.search(r"^[ \t]*::citations", facts.masked, re.M))
    uncited = []
    for line, text, written in paragraphs_of(facts.masked):
        if "[@" in written:
            continue
        terms = [*numbers_in(text), *quotations(text), *[" ".join(run) for run in name_runs(text) if len(run) > 1]]
        if terms:
            uncited.append({"line": line, "start": short(text, 60), "terms": terms})
    problems = []
    if unresolved:
        problems.append("These citation markers have no entry in the Story's citations, so they cannot be numbered: " + ", ".join(f"[@{key}]" for key in unresolved) + ".")
    if cited and not listed:
        problems.append(f"The Story has citation markers ({', '.join('[@' + key + ']' for key in sorted(set(cited)))}) but no ::citations{{}} line to say where the bibliography goes, so the page adds the bibliography at the end; put ::citations{{}} where you want it.")
    if uncited:
        problems.append(f"{many(len(uncited), 'paragraph')} with names, numbers or quotations {'cites' if len(uncited) == 1 else 'cite'} nothing: " + "; ".join(f"line {row['line']}" for row in uncited) + ".")
    evidence = {"cited": sorted(set(cited)), "unresolved": unresolved, "listedOnPage": listed, "uncited": uncited}
    if problems:
        return finding("A5", CONCERN, " ".join(problems), **evidence)
    return finding("A5", PASS, (f"Every cited Reference ({len(set(cited))}) resolves and is listed." if cited else "The Story makes no cited claims and has no uncited names, numbers or quotations."), **evidence)


def check_a8(facts: Facts) -> dict[str, Any]:
    links = [{"line": facts.masked.count("\n", 0, match.start()) + 1, "text": match.group("text").strip(), "href": match.group("href")} for match in MARKDOWN_LINK.finditer(facts.masked)]
    weak = [row for row in links if row["text"].lower().strip(" .") in WEAK_LINK_TEXTS or row["text"] == row["href"]]
    if weak:
        return finding("A8", CONCERN, "Link text that means nothing out of context: " + "; ".join(f"\"{short(row['text'], 40)}\" at line {row['line']}" for row in weak) + ".", links=weak)
    return finding("A8", PASS, f"All {many(len(links), 'link')} have meaningful text." if links else "The Story has no links.")


def check_a11(facts: Facts) -> dict[str, Any]:
    has_table = any(TABLE_RULE.match(line) for line in facts.masked.split("\n"))
    guesses = [{"line": image.line, "src": image.src} for image in facts.images if "table" in " ".join([image.alt or "", image.caption, Path(image.src).stem]).lower()]
    if guesses and not has_table:
        return finding("A11", CONCERN, "These images may be pictures of tables (a guess from their names): " + "; ".join(f"line {row['line']}" for row in guesses) + ".", images=guesses)
    return finding("A11", PASS, "No image looks like a picture of a table.")


def check_a13(facts: Facts) -> dict[str, Any]:
    if not facts.known:
        return _unknown_site("A13")
    if facts.environment.guarded:
        return finding("A13", NOT_ASSESSABLE, NOT_LIVE, production=False)
    return finding("A13", PASS, "The site is live and open to readers.", production=True)


# --- search and social --------------------------------------------------------------------------------------------------------------------

def check_s1(facts: Facts) -> dict[str, Any]:
    first = check_p1(facts)
    return finding("S1", first["state"], first["message"], title=first["evidence"]["title"], notChecked=[
        "whether another Story on this site has the same title (Papyrus has no index of titles)", "how this title's length compares with this site's other titles"])


def check_s2(facts: Facts) -> list[dict[str, Any]]:
    source = facts.preview.description_source
    words = {"summary": "the Story's own dek", "opening": "the first paragraph", "site": "the site-wide description", "none": "nothing"}
    evidence = {"source": source, "text": short(facts.preview.head.description, 300)}
    if source in ("site", "none"):
        message = (f"The description is {words[source]}, so every Story without a dek of its own shares it." if source == "site" else
                   "The Story has no description at all: no dek, no usable first paragraph and no site description.")
        return [finding(key, CONCERN, message, **evidence) for key in ("S2", "C2")]
    return [finding(key, PASS, f"The description comes from {words[source]}.", **evidence) for key in ("S2", "C2")]


def check_s4(facts: Facts) -> dict[str, Any]:
    entry = facts.entry
    data = facts.front_matter
    reasons = [name for name, on in (("draft", entry.draft), ("noindex", str(data.get("noindex", "")).lower() in ("true", "1", "yes", "on")),
                                     ("robots", "noindex" in str(data.get("robots", "")).lower())) if on]
    if entry.noindex or reasons:
        return finding("S4", CONCERN, "The Story is marked " + " and ".join(reasons or ["noindex"]) + " in its front matter, so search engines are told to leave it out. Check that is intended.",
                       noindex=True, reasons=reasons)
    note = " The site itself asks crawlers to stay away." if facts.known and facts.environment.guarded else ""
    return finding("S4", PASS, "Nothing in the Story asks search engines to leave it out." + note, noindex=False, siteGuarded=bool(facts.known and facts.environment.guarded))


def check_s5(facts: Facts) -> dict[str, Any]:
    if not facts.known:
        return _unknown_site("S5")
    explicit = facts.entry.canonical
    if explicit and not explicit.startswith(("http://", "https://")):
        return finding("S5", CONCERN, f"The Story's canonical address is not a full web address: {short(explicit)}.", canonical=explicit)
    resolved = explicit or facts.head.absolute(facts.entry.url)
    if not resolved:
        return _no_origin("S5")
    return finding("S5", PASS, f"The canonical address is {resolved}.", canonical=resolved, explicit=bool(explicit))


def check_s6(facts: Facts) -> dict[str, Any]:
    if not facts.known:
        return _unknown_site("S6")
    if facts.preview.head.json_ld_type is None:
        return finding("S6", NOT_APPLICABLE, "This kind of page carries no article structured data on this site.")
    if facts.environment.origin is None:
        return _no_origin("S6")
    blocks_found = json_ld_of(facts.head_html)
    article = next((block for block in blocks_found if block.get("@type") == facts.preview.head.json_ld_type), None)
    if article is None:
        return finding("S6", CONCERN, "No article structured data is produced for the Story.", produced=blocks_found)
    missing = [name for name in ("headline", "datePublished", "dateModified", "author", "image", "mainEntityOfPage") if not article.get(name)]
    if not (article.get("publisher") or {}).get("name"):
        missing.append("publisher name (seo.publisherName)")
    problems = []
    if missing:
        problems.append("Structured data is missing: " + ", ".join(missing) + ".")
    if article.get("headline") and article["headline"] != facts.entry.title:
        problems.append("The structured data headline differs from the page title.")
    if facts.standard.breadcrumbs and facts.standard.seo.breadcrumbs_json_ld and facts.preview.head.breadcrumbs and not any(b.get("@type") == "BreadcrumbList" for b in blocks_found):
        problems.append("The page has breadcrumbs but no breadcrumb structured data.")
    if problems:
        return finding("S6", CONCERN, " ".join(problems), produced=blocks_found, missing=missing)
    return finding("S6", PASS, "The structured data is complete and its headline matches the title.", produced=blocks_found)


def check_s7(facts: Facts) -> dict[str, Any]:
    entry = facts.entry
    if not facts.known:
        return _unknown_site("S7")
    if entry.in_sitemap:
        return finding("S7", PASS, f"The Story will be in the sitemap, last changed {entry.updated or 'on an unknown date'}.", lastmod=entry.updated or None)
    reason = ("it has no page of its own" if entry.key is None else "it is marked noindex or draft" if entry.noindex else "its section is kept out of the sitemap")
    return finding("S7", CONCERN, f"The Story will not be in the sitemap: {reason}.", reason=reason)


def check_c1(facts: Facts) -> dict[str, Any]:
    if not facts.known:
        return _unknown_site("C1")
    page = facts.head.absolute(facts.entry.url)
    image = facts.preview.head.image
    picture = facts.head.og_image(image)
    if page is None or (image and picture is None):
        return _no_origin("C1")
    return finding("C1", PASS, "The page and picture addresses can be built.", page=page, picture=picture)


def check_c3(facts: Facts) -> dict[str, Any]:
    source = facts.preview.image_source
    words = {"front_matter": "The Story has its own picture for share cards.", "body": "The share card will use the first picture in the Story's text.",
             "site_default": "This Story has no picture of its own, so a share card will use the site's default picture. Nothing to check about the picture.",
             "none": "This Story has no picture and the site has no default one, so a share card will have no picture."}
    return finding("C3", PASS, words[source], source=source)


def check_c5(facts: Facts) -> dict[str, Any]:
    head = facts.preview.head
    if facts.preview.image_source == "none":
        return finding("C5", NOT_APPLICABLE, "There is no picture on the share card.")
    alt = meta(facts.head_html, "og:image:alt") if facts.known and facts.environment.origin else head.image_alt
    if not alt and facts.known and facts.preview.image_source == "site_default":
        alt = facts.standard.seo.default_image_alt
    if alt:
        return finding("C5", PASS, "The share card's picture has a description.", alt=short(alt, 160))
    return finding("C5", CONCERN, "The share card's picture has no description. Add imageAlt to the Story's front matter.", alt=None, image=head.image)


def check_c7(facts: Facts) -> dict[str, Any]:
    from .fact_check import literal_check

    head = facts.preview.head
    texts = [facts.story.body, facts.opening]
    missing = []
    for label, text in (("title", head.title), ("description", head.description)):
        for row in literal_check(text, texts, prose=True):
            missing.append({"in": label, **row})
    if missing:
        return finding("C7", CONCERN, "These names, numbers or quotations in the share text are not in the Story: " + "; ".join(f"\"{short(row['term'], 40)}\" ({row['in']})" for row in missing) + ".", unmatched=missing)
    return finding("C7", PASS, "Every name, number and quotation in the title and description is in the Story.")


# --- running ---------------------------------------------------------------------------------------------------------------------------

#: The checks that need the Story's page under this site's settings; with none, they are not assessable and the rest still run.
PAGE_CHECKS = ("A1", "A2", "A3", "A4", "S2", "C2", "S4", "S5", "S6", "S7", "C1", "C3", "C5", "C7")


def run_checks(story: LensStory, site: LensSite | None, *, lens: str | None = None) -> list[dict[str, Any]]:
    """Every deterministic finding for one Story version, in the order of the lenses; ``lens`` limits them to one lens (a key or a step)."""
    facts = Facts(story, site)
    found = [check_p1(facts), check_p2(facts), *check_p6(facts), *check_p7(facts), check_p8(facts), *check_p10(facts), check_a5(facts), check_a8(facts),
             check_a11(facts), check_a13(facts), check_s1(facts)]
    if facts.entry is None:
        reason = "The Story has no page of its own under this site's settings, so its search, share and Markdown checks were not run."
        found += [finding(key, NOT_ASSESSABLE, reason) for key in PAGE_CHECKS]
    else:
        found += [*check_agents(facts), *check_s2(facts), check_s4(facts), check_s5(facts), check_s6(facts), check_s7(facts), check_c1(facts), check_c3(facts),
                  check_c5(facts), check_c7(facts)]
    by_key = {row["check"]: row for row in found}
    wanted = lenses.lens_named(lens) if lens else None
    out = []
    for each in lenses.LENSES:
        if wanted is not None and each is not wanted:
            continue
        out += [by_key[check.key] for check in each.checks if check.key in by_key]
    return out


def not_run(lens: str | None = None) -> list[dict[str, str]]:
    """Checks of the lens(es) this module does not run, with the reason."""
    wanted = lenses.lens_named(lens) if lens else None
    return [{"check": check.key, "title": check.title, "method": check.method, "reason": NOT_RUN.get(check.key, "not built yet")}
            for each in lenses.LENSES if wanted is None or each is wanted for check in each.checks if not check.built]


def summarize(findings: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """``{step: {state: n}}``, with a mirrored finding counted in each lens it is shown in."""
    out: dict[str, dict[str, int]] = {}
    for row in findings:
        counts = out.setdefault(row["step"], {})
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    return out


def blockers(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The error-level problems: while one stands a lens step cannot be closed as done."""
    return [row for row in findings if row["state"] == PROBLEM]
