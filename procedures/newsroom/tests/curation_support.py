"""In-memory stand-ins for curation-before-review tests (pytest and behave share them): no network, no AWS, no model."""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for path in (ROOT / "src", Path(__file__).resolve().parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from papyrus_content.link_exploration import Exploration, Response  # noqa: E402
from papyrus_content.model_attachments import model_attachment_id  # noqa: E402
from papyrus_content.reference_curation import Services  # noqa: E402
from papyrus_content.reference_curation_store import AttachmentStore  # noqa: E402
from pdf_fixtures import make_pdf  # noqa: E402

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)

ARTICLE_PARAGRAPHS = [
    "The county board voted on Tuesday to adopt the new transit plan after three hours of public comment from residents and riders.",
    "Supporters said the plan would cut average commute times by a quarter within five years, while opponents warned about the cost to taxpayers.",
    "Engineers presented a phased schedule that begins with bus lane upgrades and ends with a light rail extension to the airport.",
    "The board also approved a study of fare capping, which would limit what a rider pays in a single day or month across every line.",
    "Funding for the first phase comes from a regional grant, and the board expects to ask voters for a sales tax in the next election.",
]


def article_html(paragraphs=ARTICLE_PARAGRAPHS, *, description="Board adopts transit plan.", extra_head="", footer="") -> str:
    body = "".join(f"<p>{text}</p>" for text in paragraphs)
    return (f"<html><head><title>Transit plan</title><meta property='og:description' content='{description}'>{extra_head}</head>"
            f"<body><nav><p>Home news sports weather and a long menu of things to click on the site</p></nav>"
            f"<article><h1>County adopts transit plan</h1>{body}{footer}</article>"
            f"<footer><p>Copyright and legal boilerplate that is not part of the article at all, honest.</p></footer></body></html>")


PAPER_PARAGRAPHS = [
    "Abstract We study how small language models can be steered by retrieval over a fixed few-shot list and report consistent gains.",
    "1 Introduction Language models are used widely in newsrooms, and editors want control over what they surface to readers each day.",
    "2 Method We train a ranker on editor feedback and evaluate it against a held out set of references with known labels.",
    "References Smith 2020 Steering feeds. Jones 2021 Learning from editors.",
]


def paper_pdf() -> bytes:
    return make_pdf([[line] for line in PAPER_PARAGRAPHS])


TEI = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title level="a" type="main">Steering Feeds With Editor Feedback</title></titleStmt>
<sourceDesc><biblStruct><analytic>
<author><persName><forename type="first">Ada</forename><surname>Lovelace</surname></persName><affiliation><orgName type="institution">Analytical Engines</orgName></affiliation></author>
<author><persName><forename type="first">Grace</forename><surname>Hopper</surname></persName></author>
<idno type="DOI">10.1234/steer.2026</idno></analytic></biblStruct></sourceDesc></fileDesc>
<profileDesc><abstract><div><p>We steer small models with editor feedback.</p></div></abstract></profileDesc></teiHeader>
<text><body><div><head n="1">Introduction</head><p>Editors want control.</p></div><div><head n="2">Method</head><p>We train a ranker.</p></div></body>
<back><div><listBibl><biblStruct><analytic><title level="a">Steering feeds</title><author><persName><forename>J</forename><surname>Smith</surname></persName></author></analytic>
<monogr><title level="j">Journal of Feeds</title><imprint><date type="published" when="2020-05-01"/></imprint></monogr><idno type="DOI">10.1/feeds</idno></biblStruct></listBibl></div></back></text></TEI>
"""


class MemoryClient:
    """Reference and ReferenceAttachment tables in memory, with the calls curation makes."""

    def __init__(self, references=()):
        self.tables = {"Reference": {r["id"]: copy.deepcopy(r) for r in references}, "ReferenceAttachment": {}, "ModelAttachment": {}}
        self.writes = 0

    def get_record(self, model, record_id):
        row = self.tables.setdefault(model, {}).get(record_id)
        return copy.deepcopy(row) if row else None

    def list_records(self, model):
        return [copy.deepcopy(r) for r in self.tables.setdefault(model, {}).values()]

    def upsert(self, model, row):
        self.writes += 1
        self.tables.setdefault(model, {})[row["id"]] = copy.deepcopy(row)
        return "created"

    def card(self, reference_id):
        for row in self.tables["ReferenceAttachment"].values():
            if row.get("role") == "curation" and row.get("referenceId") == reference_id:
                return json.loads(row["metadata"])
        return None


class MemoryStore(AttachmentStore):
    """ModelAttachment bodies in a dict, keyed like the real ones."""

    def __init__(self, client):
        super().__init__(client)
        self.bodies: dict[str, bytes] = {}
        self.writes: list[str] = []

    def write(self, reference, sort_key, filename, media_type, content, now):
        key = model_attachment_id("reference", reference["id"], "metadata", sort_key)
        self.bodies[key] = content.encode("utf-8") if isinstance(content, str) else content
        self.writes.append(sort_key)
        self.client.tables["ModelAttachment"][key] = {"id": key, "sortKey": sort_key, "mediaType": media_type, "filename": filename}
        return {"id": key}

    def read(self, reference, sort_key):
        return self.bodies.get(model_attachment_id("reference", reference["id"], "metadata", sort_key))

    def text(self, reference, sort_key):
        body = self.read(reference, sort_key)
        return body.decode("utf-8") if body is not None else None

    def upload(self, reference_id, body: bytes, *, name="curation-upload-pdf-1", media_type="application/pdf", owner_kind="reference"):
        """An editor's upload as the two-step upload leaves it: a ModelAttachment row and its stored bytes. Returns the attachment id."""
        attachment_id = model_attachment_id(owner_kind, reference_id, "curation-upload-pdf", name)
        self.bodies[attachment_id] = body
        self.client.tables["ModelAttachment"][attachment_id] = {"id": attachment_id, "ownerKind": owner_kind, "ownerId": reference_id,
            "role": "curation-upload-pdf", "sortKey": name, "filename": "paper.pdf", "mediaType": media_type, "byteSize": len(body)}
        return attachment_id

    def get_attachment(self, attachment_id):
        return self.client.get_record("ModelAttachment", attachment_id)

    def download(self, attachment):
        return self.bodies.get(attachment["id"])


def reference(name="r1", **fields):
    return {"id": f"{name}-v1", "lineageId": name, "versionNumber": 1, "versionState": "current", "corpusId": "knowledge-corpus-site",
            "curationStatus": "pending", "title": f"Title {name}", "sourceUri": f"https://news.example.org/{name}", **fields}


def page(body: str, content_type="text/html; charset=utf-8", *, truncated=False) -> Response:
    return Response(200, {"content-type": content_type}, body.encode("utf-8") if isinstance(body, str) else body, truncated=truncated)


class Explorer:
    """Stands in for link exploration: a table from address to a Response (or a typed failure string)."""

    def __init__(self, pages):
        self.pages = dict(pages)
        self.asked: list[str] = []

    def __call__(self, url, context=None, **kwargs):
        self.asked.append(url)
        found = self.pages.get(url)
        if found is None:
            return Exploration(False, None, failure="http_4xx", direct_failure="http_4xx")
        if isinstance(found, str):
            return Exploration(False, None, failure=found, direct_failure=found)
        return Exploration(True, url, None, "direct", readable=False, response=found if kwargs.get("keep_response") else None)


class Summarizer:
    def __init__(self, text="Transit plan adopted; phased bus and rail work begins with a regional grant.", fail_with=None):
        self.text, self.fail_with, self.calls = text, fail_with, []

    def __call__(self, request):
        from papyrus_content.reference_curation import SUMMARY_MODEL, SUMMARY_PROMPT_VERSION, SummaryFailed

        self.calls.append(request)
        if self.fail_with:
            raise SummaryFailed(self.fail_with)
        return {"text": self.text, "model": SUMMARY_MODEL, "promptVersion": SUMMARY_PROMPT_VERSION, "inputTruncated": False,
                "usage": {"inputTokens": 100, "cachedInputTokens": 0, "outputTokens": 20}}


class Grobid:
    def __init__(self, tei=TEI, status=200):
        self.tei, self.status, self.calls = tei, status, 0

    def __call__(self, endpoint, **kwargs):
        self.calls += 1
        return type("Response", (), {"status_code": self.status, "text": self.tei})()


def services(client, *, pages=None, summarizer="default", grobid_url=None, grobid=None, now=NOW):
    store = MemoryStore(client)
    return Services(store=store, summarizer=Summarizer() if summarizer == "default" else summarizer, grobid_url=grobid_url,
                    grobid_post=grobid, explorer=Explorer(pages or {}), now=lambda: now)
