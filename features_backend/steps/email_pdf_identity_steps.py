from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from papyrus_newsroom.email_pdf_intake import (
    citation_url_for_identifiers,
    external_item_id_for_identifiers,
    extract_pdf_intake_identifiers,
    find_reference_by_external_item_id,
)

CORPUS_THAT_RECEIVES_EMAILED_PAPERS = "knowledge-corpus-emailed-papers"
NO_HEADER_EXTRACTION_SERVICE = ""


class CorpusLookupRecorder:
    def __init__(self, references_already_in_the_corpus):
        self.references_already_in_the_corpus = references_already_in_the_corpus
        self.lookups = []

    def graphql(self, query, variables):
        self.lookups.append(variables)
        return {"listReferencesByCorpusAndExternalItem": {"items": self.references_already_in_the_corpus}}


@given('an emailed PDF that contains the text "{text_inside_the_pdf}"')
def given_emailed_pdf(context, text_inside_the_pdf):
    context.emailed_pdf_bytes = b"%PDF-1.4\n" + text_inside_the_pdf.encode("latin-1") + b"\n%%EOF"


@when("Papyrus reads the paper's identifiers")
def when_identifiers_are_read(context):
    context.paper_identifiers = extract_pdf_intake_identifiers(
        context.emailed_pdf_bytes,
        grobid_url=NO_HEADER_EXTRACTION_SERVICE,
    )


@then('the paper\'s DOI is "{doi}"')
def then_paper_doi_is(context, doi):
    assert context.paper_identifiers["doi"] == doi, context.paper_identifiers


@then('the paper\'s arXiv number is "{arxiv_number}"')
def then_paper_arxiv_number_is(context, arxiv_number):
    assert context.paper_identifiers["arxiv_id"] == arxiv_number, context.paper_identifiers


@then('the Reference identity is "{identity}"')
def then_reference_identity_is(context, identity):
    assert external_item_id_for_identifiers(context.paper_identifiers) == identity, context.paper_identifiers


@then('the citation link is "{link}"')
def then_citation_link_is(context, link):
    assert citation_url_for_identifiers(context.paper_identifiers) == link, context.paper_identifiers


@then("the paper has no Reference identity")
def then_paper_has_no_identity(context):
    assert external_item_id_for_identifiers(context.paper_identifiers) is None, context.paper_identifiers


@then("the paper has no citation link")
def then_paper_has_no_citation_link(context):
    assert citation_url_for_identifiers(context.paper_identifiers) is None, context.paper_identifiers


@then('the identifiers were found by "{method}"')
def then_identifiers_were_found_by(context, method):
    assert context.paper_identifiers["method"] == method, context.paper_identifiers


@given('the corpus already holds these References for "{identity}"')
def given_corpus_holds_references(context, identity):
    context.corpus_lookup_recorder = CorpusLookupRecorder(
        [
            {"id": row["id"], "versionState": row["version state"], "externalItemId": identity}
            for row in context.table
        ]
    )


@given('the corpus holds no Reference for "{identity}"')
def given_corpus_holds_no_reference(context, identity):
    context.corpus_lookup_recorder = CorpusLookupRecorder([])


@when('Papyrus looks for a Reference with the identity "{identity}"')
def when_reference_is_looked_up(context, identity):
    context.identity_looked_up = identity
    context.reference_found_for_identity = find_reference_by_external_item_id(
        context.corpus_lookup_recorder,
        corpus_id=CORPUS_THAT_RECEIVES_EMAILED_PAPERS,
        external_item_id=identity,
    )


@then('it finds the Reference "{reference_id}"')
def then_it_finds_reference(context, reference_id):
    assert context.reference_found_for_identity["id"] == reference_id, context.reference_found_for_identity


@then("it finds no Reference")
def then_it_finds_no_reference(context):
    assert context.reference_found_for_identity is None


@then("it asked only for that identity in that corpus")
def then_it_asked_only_for_that_identity(context):
    assert len(context.corpus_lookup_recorder.lookups) == 1
    lookup = context.corpus_lookup_recorder.lookups[0]
    assert lookup["corpusId"] == CORPUS_THAT_RECEIVES_EMAILED_PAPERS
    assert lookup["externalItemId"] == context.identity_looked_up
