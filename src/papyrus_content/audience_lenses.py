"""The one definition of the four lenses a Story is reviewed through (docs/four-lens-review.md; PPY-59c772).

Pure data and pure functions, no model calls, in the same style as ``newsroom_process.py``. Everything else is generated from it: the table in
``docs/four-lens-review.md`` (a test fails when the committed table differs), the context-pack layer every agent reads, the lens lines of
``papyrus stories next`` and, through ``lens_evidence.py``, the checks ``papyrus stories lens-check`` runs.

The four ``step`` keys are the checklist's review steps (``review_people``, ``review_reader_agents``, ``review_search``, ``review_social``).
The checklist itself lives in ``newsroom_process.py`` and ``story_checklist.py``; this module only names the steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

#: Raise it whenever a check's meaning changes, so stored evidence can say which definition it was made under.
LENS_VERSION = 1

AUTO, JEV, LUNA, HUMAN = "auto", "jev", "luna", "human"
METHODS = (AUTO, JEV, LUNA, HUMAN)
METHOD_WORDS = {AUTO: "checked by code", JEV: "judged by Jev", LUNA: "drafted by Luna", HUMAN: "a person decides"}

INFO, WARN, ERROR = "info", "warn", "error"
SEVERITIES = (INFO, WARN, ERROR)

#: What a check can report. ``not_assessable`` is neither a pass nor a failure: it means Papyrus could not tell.
PASS, CONCERN, PROBLEM, NOT_ASSESSABLE, NOT_APPLICABLE = "pass", "concern", "problem", "not_assessable", "not_applicable"
STATES = (PASS, CONCERN, PROBLEM, NOT_ASSESSABLE, NOT_APPLICABLE)

COPYWRITER, EDITOR, REPORTER = "copywriter", "editor", "reporter"


@dataclass(frozen=True)
class Check:
    key: str
    title: str
    method: str
    #: The default severity. ``None`` for a judgment only a person can make: it has no severity because it is not a finding.
    severity: str | None
    #: What the finding shows when it is opened.
    evidence: str
    #: The agent roles that read this check in their context pack, because they can satisfy it while they work.
    roles: tuple[str, ...] = ()
    #: The yes/no or pick-one question a decision-model check asks. Model-judged checks are not built yet.
    question: str | None = None
    #: Checks in other lenses that report the same fact, asked or computed once and shown in each lens.
    mirrors: tuple[str, ...] = ()
    #: True once ``papyrus stories lens-check`` runs it.
    built: bool = False


@dataclass(frozen=True)
class Lens:
    key: str
    step: str
    title: str
    audience: str
    good: str
    note: str
    checks: tuple[Check, ...]

    @property
    def error_checks(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if check.severity == ERROR)


def _c(key: str, title: str, method: str, severity: str | None, evidence: str, roles: tuple[str, ...] = (), *, question: str | None = None,
       mirrors: tuple[str, ...] = (), built: bool = False) -> Check:
    return Check(key, title, method, severity, evidence, roles, question, mirrors, built)


_CW, _ED, _RP = COPYWRITER, EDITOR, REPORTER

PEOPLE = Lens(
    key="people", step="review_people", title="Reviewed for readers", audience="people reading or skimming the page",
    good=("A person who lands on the page, or skims it, gets an accurate headline, a dek that adds something, an opening that earns the next paragraph, "
          "headings that say something, pictures that are credited and described, and prose that does not read as machine filler. The Story is true: "
          "every claim a model wrote has been through the fact check."),
    note="Human readers: read the Story as a reader would, run the checks, fix what you can and record the findings.",
    checks=(
        _c("P1", "The headline is present, is not a placeholder and is not another Story's headline", AUTO, WARN, "the title, and the other Story if duplicated", (_CW, _ED), built=True),
        _c("P2", "The Story has a dek (the summary line under the headline)", AUTO, WARN, "which field was used, or that the page will use the first paragraph", (_CW, _ED), built=True),
        _c("P3", "The dek adds something the headline does not", JEV, INFO, "the question, the answer and its probability", (_CW,),
           question="Does the dek say anything the headline does not?"),
        _c("P4", "The headline does not promise what the Story does not deliver", JEV, WARN, "the question, the answer and the sentence compared", (_CW,),
           question="Does the headline claim or imply something the Story does not support?"),
        _c("P5", "The opening paragraph works as an opening", JEV, INFO, "the question and the answer", (_CW,),
           question="Could someone who read only the first paragraph say what this Story is about?"),
        _c("P6", "The headings are informative and in order", AUTO, INFO, "the heading outline as read", (_CW, _ED), mirrors=("A9",), built=True),
        _c("P7", "Every image has alt text; an empty alt counts only as a deliberate decoration", AUTO, ERROR,
           "each image with its alt text present, empty or missing", (_CW, _ED), mirrors=("A10",), built=True),
        _c("P8", "Alt text is not a filename, the word \"image\" or a copy of the caption", AUTO, WARN, "the alt texts at fault", (_CW,), built=True),
        _c("P9", "Alt text describes what the image shows", LUNA, WARN, "the drafted text, the accepted text and who accepted it", (_CW, _ED)),
        _c("P10", "Every third-party image is credited", AUTO, ERROR,
           "each image, where it came from and the credit found or missing", (_CW, _ED, _RP), mirrors=("C6",), built=True),
        _c("P11", "The prose is not machine filler or keyword stuffing", AUTO, WARN, "the editorial check run and its top findings", (_CW,)),
        _c("P12", "Charts and diagrams carry their meaning by marks and labels, not by colour alone", HUMAN, INFO,
           "one question per figure and whether a person looked", (_CW, _ED)),
        _c("P13", "Every claim a model wrote has been fact-checked", AUTO, WARN, "claims held, by group, or that the draft check has not run", (_CW, _RP)),
        _c("P14", "The Story is fair, engaging and worth reading", HUMAN, None, "the person's findings note", (_ED,)),
        _c("P15", "The readability is typical for this site", AUTO, INFO, "the Story's value against the site's own median and spread"),
        _c("P16", "Every video has a title (its accessible name) and a credit", AUTO, ERROR,
           "each video, its title and credit, and whatever is missing", (_CW, _ED, _RP), built=True),
        _c("P17", "Every video has a caption", AUTO, WARN, "the videos with no caption", (_CW, _ED), built=True),
        _c("P18", "A video plays on this site: the site lists its provider", AUTO, WARN, "the site's embeds setting, each video's provider", (_ED,), built=True),
    ),
)

READER_AGENTS = Lens(
    key="agents", step="review_reader_agents", title="Reviewed for AI reader agents", audience="AI agents that read the page for a person",
    good=("An agent that is allowed to read the page for a person gets the Story as the author wrote it (verbatim Markus, not flattened Markdown), "
          "knows who wrote it and when, can tell each claim from the source it cites, and loses nothing if it reads only the Markdown copy. "
          "Where an agent cannot reach the page, the review says so and does not assume."),
    note="AI agents that read the page for a person: check the Markdown copy matches the source, then record the findings.",
    checks=(
        _c("A1", "A Markdown copy will exist for this Story", AUTO, WARN, "the site setting, the Story's flags and the expected path", (_ED,), built=True),
        _c("A2", "The Markdown copy is the Story's Markus source, every directive intact", AUTO, ERROR, "both versions' hashes and the first line that differs", (), built=True),
        _c("A3", "Nothing the Markdown copy leaves out changes what an agent learns", AUTO, WARN, "each left-out block, its line and that it has no text equivalent", (_CW,), built=True),
        _c("A4", "The Markdown copy carries the title, summary, byline, dates and canonical address", AUTO, WARN, "the header lines produced", (), built=True),
        _c("A5", "Each outside claim cites a Reference and every citation resolves", AUTO, WARN, "cited keys, unresolved keys and uncited paragraphs with names, numbers or quotations", (_CW, _RP), built=True),
        _c("A6", "Claims can be told apart from their sources: attribution is explicit", JEV, WARN, "the question, the answer and the paragraph", (_CW, _RP),
           question="Does this paragraph state as fact something the cited source only attributes to a party?"),
        _c("A7", "The first two paragraphs alone do not misstate the Story's conclusion", JEV, WARN, "the question and the answer", (_CW,),
           question="If a reader saw only the first two paragraphs, would they come away believing something the whole Story contradicts?"),
        _c("A8", "Link text makes sense out of context", AUTO, INFO, "the weak link texts", (_CW,), built=True),
        _c("A9", "The headings form an outline an agent can navigate", AUTO, INFO, "the outline", (_CW, _ED), mirrors=("P6",), built=True),
        _c("A10", "Images have a text equivalent in the Markdown copy", AUTO, WARN, "the images without one", (_CW,), mirrors=("P7",), built=True),
        _c("A11", "Tables are tables, not pictures of tables", AUTO, INFO, "images that look like tables (a guess)", (_CW,), built=True),
        _c("A12", "After publishing: the Markdown copy is served and the page links to it", AUTO, WARN, "the addresses fetched, their status and content type"),
        _c("A13", "The site is live and open to readers", AUTO, INFO, "whether the site asks readers to stay away", built=True),
        _c("A14", "The Story does not claim access to a source it did not read", HUMAN, None, "the person's findings note", (_RP,)),
        _c("A15", "A credited video is one of the Story's citations", AUTO, WARN, "the credited videos whose address is not among the citations", (_CW, _RP), built=True),
    ),
)

SEARCH = Lens(
    key="search", step="review_search", title="Reviewed for search", audience="search crawlers",
    good=("The page can be found and describes itself truthfully: a descriptive, unique title, a description written for people that fits the opening, "
          "the right canonical address, indexable when meant to be and not otherwise, structured data that is valid and matches the visible page, "
          "links from the rest of the site, and the topic's real terms because the Story is about them. Copy is never made worse to satisfy this lens."),
    note="Search crawlers: check the title, description, canonical address and structured data, then record the findings.",
    checks=(
        _c("S1", "The title is present, descriptive and unique among the site's Stories", AUTO, WARN, "the title, any duplicates and whether it is an outlier here", (_CW, _ED), built=True),
        _c("S2", "The description is the Story's own, not the site-wide fallback", AUTO, WARN, "which source the description came from", (_CW, _ED), mirrors=("C2",), built=True),
        _c("S3", "The description and title match the Story", JEV, WARN, "the stored answer", (_CW,),
           question="Does the title or description claim something the Story does not support?"),
        _c("S4", "Indexing is as intended", AUTO, WARN, "the flags and where they came from", (_ED,), built=True),
        _c("S5", "The canonical address is correct", AUTO, WARN, "the resolved canonical address", (), built=True),
        _c("S6", "Structured data is complete and matches the page", AUTO, WARN, "the structured data produced and the missing fields", (), built=True),
        _c("S7", "The Story will be in the sitemap with a last-changed date", AUTO, WARN, "the rule that applied", (), built=True),
        _c("S8", "The Story is linked from the rest of the site", AUTO, INFO, "links in and out", (_ED,)),
        _c("S9", "The Story addresses the search targets it is meant for", JEV, INFO, "the targets checked and the answers", (_ED, _RP),
           question="Is this Story substantively about <concept>?"),
        _c("S10", "Target terms are used naturally, not stuffed", JEV, WARN, "counts against the site's history and the flagged passages", (_CW,),
           question="Does any passage repeat a topic term in a way a person would find unnatural?"),
        _c("S11", "The Story uses the name a reader would search for", JEV, INFO, "the answers", (_CW,),
           question="Does the Story use a name for this topic that a reader would search for, and not only an internal name?"),
        _c("S12", "After publishing: the live page matches what was predicted", AUTO, WARN, "the fetch results"),
        _c("S13", "Search engines have indexed the page", AUTO, INFO, "no evidence exists in Papyrus either way"),
        _c("S14", "The copy reads as written for people first", HUMAN, None, "the person's findings note", (_ED,)),
    ),
)

SOCIAL = Lens(
    key="social", step="review_social", title="Reviewed for social previews", audience="people who see a link card before they click",
    good=("The three things a person sees in a share card (title, description, picture) are accurate, readable on their own, informative if the person "
          "never clicks, and consistent with the Story. The picture is real, credited if it is not ours, and described. If the Story has no picture of its "
          "own, the site's generic picture is used knowingly."),
    note="Social previews (link cards): check the title, description and picture a share card will show, then record the findings.",
    checks=(
        _c("C1", "The preview resolves: the page and picture addresses can be built", AUTO, WARN, "the resolved addresses", (), built=True),
        _c("C2", "The description is the Story's own, not the site fallback", AUTO, WARN, "which source the description came from", (_CW,), mirrors=("S2",), built=True),
        _c("C3", "The Story has its own picture, or is knowingly using the site's", AUTO, INFO, "where the picture came from", (_ED,), built=True),
        _c("C4", "The share picture file exists, is a JPEG or PNG and its size and shape are known", AUTO, WARN, "the address, status, Content-Type, format, size and ratio", (_ED,), built=True),
        _c("C5", "The picture has a description for the share card", AUTO, WARN, "the description used, or that none is emitted", (_CW,), built=True),
        _c("C6", "A third-party picture is credited", AUTO, ERROR, "as P10", (_CW, _ED), mirrors=("P10",), built=True),
        _c("C7", "Every name, number and quotation in the title and description is in the Story", AUTO, WARN, "the terms not found", (_CW,), built=True),
        _c("C8", "The preview does not mislead", JEV, WARN, "the answer and its probability", (_CW,),
           question="Taken alone, do the title, description and picture give a false impression of what the Story says?"),
        _c("C9", "The preview stands alone as information", JEV, INFO, "the answer", (_CW,),
           question="Does the description tell someone who never clicks what the Story found?"),
        _c("C10", "The preview is not a teaser that withholds the point", JEV, INFO, "the choice and its probability", (_CW,),
           question="Which best describes the description: informs, teases, withholds?"),
        _c("C11", "A drawn approximation of the card is shown to the approver", AUTO, INFO, "the approximation and its inputs"),
        _c("C12", "After publishing: the live og:image and twitter:image equal the tested picture and it can be fetched", AUTO, WARN, "the fetch results"),
        _c("C13", "The picture is tasteful, on brand and relevant", HUMAN, None, "the person's findings note", (_ED,)),
    ),
)

LENSES: tuple[Lens, ...] = (PEOPLE, READER_AGENTS, SEARCH, SOCIAL)
LENS_BY_KEY = {lens.key: lens for lens in LENSES}
LENS_BY_STEP = {lens.step: lens for lens in LENSES}
LENS_STEP_KEYS = tuple(lens.step for lens in LENSES)
CHECK_BY_KEY = {check.key: check for lens in LENSES for check in lens.checks}


def lens_named(name: str) -> Lens:
    """A lens by its key (``people``), its step (``review_people``) or the agents lens's longer name."""
    found = LENS_BY_KEY.get(name) or LENS_BY_STEP.get(name) or LENS_BY_KEY.get({"reader_agents": "agents", "reader-agents": "agents"}.get(name, ""))
    if found is None:
        raise ValueError(f"Unknown lens {name!r}; known: {', '.join(LENS_BY_KEY)}.")
    return found


def has_checks_built() -> bool:
    return any(check.built for check in CHECK_BY_KEY.values())


# --- the checklist seam ----------------------------------------------------------------------------------------------------------

def lens_step_states(client: Any, lineage: str) -> dict[str, str]:
    """Each lens step's recorded state, ``{step key: state}``, read from the Story's checklist: the four ``review_*`` sub-task Items
    (``story_checklist.py``; one index read by parent). A Story with no checklist yet, or one that cannot be read, knows nothing, so every lens step
    reads as not checked yet."""
    from .story_checklist import read_steps

    try:
        rows = read_steps(client, lineage)
    except Exception:  # noqa: BLE001 - an unreadable checklist is "not checked yet", never a failure of `stories next`
        return {}
    return {row["stepKey"]: row["state"] for row in rows if row["stepKey"] in LENS_BY_STEP}


# --- generated text --------------------------------------------------------------------------------------------------------------

TRADE_OFFS = ("The lenses can pull against each other. Accuracy and natural writing beat every lens: do not stuff keywords, do not write a teaser that "
              "misleads, and do not make the copy worse to satisfy a lens.")

AGENT_DUTY = ("These review steps are mainly for agents to do before a person reviews the Story, so obvious problems are fixed before any human time is "
              "spent. An agent may complete a lens step, and it is recorded under the agent's name. Only a person gives the final approval.")

MUST_FIX = ("Four problems must be fixed before a step can be closed as done: an image with no alt text, a third-party image with no credit, a video with no title or no credit, and a "
            "Markdown copy that differs from the Story's source. Sites that publish without a person's approval depend on these checks even more.")


def check_command(lineage: str = "LINEAGE", lens: str | None = None) -> str:
    return f"papyrus stories lens-check --story {lineage}" + (f" --lens {lens}" if lens else "")


def _marker(check: Check) -> str:
    if check.severity == ERROR:
        return " (must be fixed before the step can close)"
    if check.method == HUMAN:
        return " (a person decides)"
    return ""


def layer_text(role: str) -> str:
    """The context-pack text for one agent role: what each lens wants and the checks that role can satisfy while it works."""
    lines = ["How this Story will be reviewed for four audiences: people, AI reader agents, search crawlers and social previews.", "", TRADE_OFFS, "", AGENT_DUTY]
    if has_checks_built():
        lines += ["", f"Run `{check_command()}`, fix what you can, then record what you found against each step. " + MUST_FIX]
    else:
        lines += ["", MUST_FIX]
    for lens in LENSES:
        mine = [check for check in lens.checks if role in check.roles]
        if not mine:
            continue
        lines += ["", f"{lens.title} ({lens.step}). Audience: {lens.audience}."]
        if role == COPYWRITER or role == EDITOR:
            lines.append(lens.good)
        lines += [f"- {check.title}{_marker(check)}" for check in mine]
    return "\n".join(lines)


def lens_lines(states: Mapping[str, str] | None = None, counts: Mapping[str, Mapping[str, int]] | None = None, lineage: str = "LINEAGE") -> list[str]:
    """One ``lens`` line per lens step that is not done, for ``papyrus stories next``.

    ``counts`` is ``{step: {state: n}}`` from stored evidence of the current version; with none a lens reads "not checked yet"."""
    lines = []
    for lens in LENSES:
        if (states or {}).get(lens.step) in ("done", "skipped", "not_applicable"):
            continue
        found = (counts or {}).get(lens.step)
        if (states or {}).get(lens.step) == "stale":
            summary = "STALE: recorded done against an earlier version of the Story"
        elif found:
            summary = "\t".join(f"{label}: {found.get(state, 0)}" for state, label in STATE_LABELS)
        else:
            summary = "not checked yet"
        lines.append("\t".join(["lens", lens.step, summary, check_command(lineage, lens.key) if has_checks_built() else f"no automatic checks yet; audience: {lens.audience}"]))
    return lines


def lens_payload(states: Mapping[str, str] | None = None, counts: Mapping[str, Mapping[str, int]] | None = None, lineage: str = "LINEAGE") -> list[dict[str, Any]]:
    return [{"step": lens.step, "lens": lens.key, "title": lens.title, "audience": lens.audience, "state": (states or {}).get(lens.step) or "not_done",
             "counts": dict((counts or {}).get(lens.step) or {}) or None,
             "command": check_command(lineage, lens.key) if has_checks_built() else None} for lens in LENSES]


#: Display order and plain words of the finding states; each is shown with a word, never colour alone.
STATE_LABELS = ((PASS, "Looks fine"), (CONCERN, "Needs a look"), (PROBLEM, "Problem"), (NOT_ASSESSABLE, "Could not check"))


# --- the documentation table -----------------------------------------------------------------------------------------------------

DOC_BEGIN = "<!-- lenses:begin (generated from src/papyrus_content/audience_lenses.py; do not edit by hand) -->"
DOC_END = "<!-- lenses:end -->"


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def docs_table() -> str:
    """The Markdown tables of docs/four-lens-review.md, one per lens."""
    out = []
    for lens in LENSES:
        out += [f"### {lens.title} (`{lens.step}`)", "", f"Audience: {lens.audience}.", "", f"**What good looks like.** {lens.good}", "",
                "| Check | What it asks | Method | Severity | Evidence | Runs in lens-check |", "| --- | --- | --- | --- | --- | --- |"]
        for check in lens.checks:
            severity = check.severity or "n/a"
            runs = "yes" if check.built else "not yet"
            out.append(f"| {check.key} | {_cell(check.title)} | {METHOD_WORDS[check.method]} | {severity} | {_cell(check.evidence)} | {runs} |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def docs_block() -> str:
    return f"{DOC_BEGIN}\n\n{docs_table()}\n{DOC_END}"


def docs_with_table(text: str) -> str:
    """``text`` (the document) with the generated block replaced."""
    start, end = text.index(DOC_BEGIN), text.index(DOC_END) + len(DOC_END)
    return text[:start] + docs_block() + text[end:]


if __name__ == "__main__":   # python -m papyrus_content.audience_lenses: rewrite the table in docs/four-lens-review.md
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "docs" / "four-lens-review.md"
    path.write_text(docs_with_table(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"wrote {path}")
