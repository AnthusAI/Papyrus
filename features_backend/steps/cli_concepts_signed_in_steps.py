"""A signed-in editor manages concepts from the CLI (features_backend/cli-concepts-signed-in.feature).

The CLI half runs the real commands against a stand-in for the site that records every mutation they send. The site's half runs the real code of the
site's routes in `scripts/test-concept-management.ts`, one named test per step, and the wiki's half runs `procedures/newsroom/tests/test_wiki_concept_addresses.py`.
No network, login or AWS.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import section_concepts, signed_in_concepts  # noqa: E402
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient  # noqa: E402
from papyrus_content.knowledge_snapshot import commands  # noqa: E402
from papyrus_content.signed_in_concepts_test import NODES, Site  # noqa: E402

LAMBDA_TEST = "scripts/test-concept-management.ts"


def lambda_behaviour(context, pattern: str) -> None:
    """The named behaviour of the site's own code holds: one node test, found by its name."""
    done = subprocess.run(["node", "--import", "tsx", "--test", "--test-reporter=spec", f"--test-name-pattern={re.escape(pattern)}", LAMBDA_TEST], cwd=REPO_ROOT, capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stdout + done.stderr
    assert re.search(r"^ℹ pass [1-9]", done.stdout, re.M) and re.search(r"^ℹ fail 0", done.stdout, re.M), done.stdout


def wiki_behaviour(pattern: str) -> None:
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-k", pattern, "procedures/newsroom/tests/test_wiki_concept_addresses.py"], cwd=REPO_ROOT,
                          capture_output=True, text=True, timeout=240, env={**__import__("os").environ, "PYTHONPATH": f"{REPO_ROOT / 'src'}:{REPO_ROOT}"})
    assert done.returncode == 0 and " passed" in done.stdout, done.stdout + done.stderr


class SignedInClient(PapyrusGraphQLAuthoringClient):
    """A client that sends a signed-in person's token (it has a header factory), whose requests go to the stand-in site."""

    def __init__(self, site: Site) -> None:
        super().__init__(endpoint="https://example.test/graphql", header_factory=lambda _payload: {"authorization": "id-token"}, site_tenant=False)
        self.site = site

    def graphql(self, query, variables=None):
        return self.site.graphql(query, variables)

    def list_records(self, model_name):
        return self.site.list_records(model_name)

    safe_list_records = list_records

    def update_record(self, model_name, payload):   # a direct write: an editor's token has no right to it
        raise AssertionError(f"a model was written directly: {model_name} {payload}")

    create_record = update_record


def run(context, function, flags, **kwargs):
    out = io.StringIO()
    context.error = None
    try:
        with contextlib.redirect_stdout(out):
            function(flags, **kwargs)
    except ValueError as error:
        context.error = str(error)
    context.output = out.getvalue()


def sent(context):
    return context.site.calls


@given("the CLI is signed in to a site as an editor and has no AWS credentials")
def _signed_in(context):
    context.site = Site()
    context.client = SignedInClient(context.site)
    context.section = {"id": "security", "coreConcepts": None}
    context.section_writes = []


@given('the site knows the concepts "containment" and "confinement problem"')
def _known(context):
    assert [row["displayName"] for row in NODES[:2]] == ["containment", "confinement problem"]


def add_core_concept(context, concept, extra=()):
    context.client.update_record = lambda model, payload: context.section_writes.append((model, payload))   # a section is the editor's own to write
    with mock.patch.object(section_concepts, "create_authoring_client", return_value=(context.client, None)), mock.patch.object(section_concepts, "find_section", return_value=context.section):
        run(context, lambda flags: section_concepts.sections_concepts(flags), ["add", "--section", "security", "--concept", concept, "--create", *extra])
    assert context.error is None, context.error


@when('the editor adds the core concept "{concept}" to a section, asking for it to be made')
def _add(context, concept):
    context.site.calls.clear()
    add_core_concept(context, concept)


@when('the editor adds the core concept "{concept}" with the name "{name}", asking for it to be made')
def _add_named(context, concept, name):
    context.site.calls.clear()
    add_core_concept(context, concept, ["--display-name", name])


@then('the CLI asks the site to make a concept named "{name}"')
def _asked(context, name):
    made = [variables for field, variables in sent(context) if field == "createEditorConcept"]
    assert made and made[-1]["displayName"] == name, sent(context)


@then("the site keeps those capitals in the name and the lower-case words in the key")
def _capitals(context):
    lambda_behaviour(context, "a concept keeps the capitalisation the person typed")


@then("a name that is not the same words as the key is refused")
def _mismatch(context):
    lambda_behaviour(context, "a name that is not the same words as the key is refused")


@when('the editor renames "{key}" to "{name}" and adds the alias "{alias}"')
def _rename(context, key, name, alias):
    context.site.calls.clear()
    with mock.patch.object(commands, "authoring_client", return_value=context.client), mock.patch.object(commands, "select_backend"):
        run(context, lambda flags: commands.knowledge_entities_rename(flags), ["--key", key, "--name", name, "--actor", "human", "--actor-name", "Ada Reader"])
        assert context.error is None, context.error
        run(context, lambda flags: commands.knowledge_entities_alias(flags), ["--key", key, "--add", alias, "--actor", "human", "--actor-name", "Ada Reader"])
        assert context.error is None, context.error


@then("the CLI sends the changes to the site's review route and writes no model")
def _review_route(context):
    fields = [field for field, _variables in sent(context)]
    assert fields == ["applyKnowledgeReview", "applyKnowledgeReview"], fields
    sent_patches = [patch for _field, variables in sent(context) for patch in json.loads(variables["patches"])]
    assert {patch["modelName"] for patch in sent_patches} == {"SemanticNode"}
    assert any(patch["expected"].get("displayName") == "Containment" for patch in sent_patches)
    assert any("the containment issue" in (patch["expected"].get("aliases") or []) for patch in sent_patches)


@then("the site writes the new name and the alias and keeps the concept's key")
def _site_writes(context):
    lambda_behaviour(context, "a rename and an alias are written")


@when("a review asks to change a concept's kind, key, status to something unknown, or to write free text or an email address, or to touch another model")
def _bad_review(context):
    context.bad_review = True


@then("the site refuses the whole review and writes nothing")
def _refuses(context):
    lambda_behaviour(context, "a review may not change what it does not review")


@given('the concept "Containment" has a description a model wrote')
def _model_description(context):
    context.node = {**NODES[0], "description": "Keeping a capable system inside its limits.", "changeReason": "Described by an editor"}
    context.nodes = [context.node, *NODES[1:]]
    context.site.list_records = lambda model: [dict(row) for row in context.nodes]
    context.client.list_records = context.site.list_records


def accept_description(context, actor):
    context.site.calls.clear()
    with mock.patch.object(commands, "authoring_client", return_value=context.client), mock.patch.object(commands, "select_backend"):
        run(context, lambda flags: commands.knowledge_entities_accept_description(flags), ["--key", "editor_concept--containment", "--actor", actor, "--actor-name", "Ada Reader"])


@when("the editor tries to accept it as an AI agent")
def _accept_ai(context):
    accept_description(context, "ai")


@then("the CLI refuses: only a person accepts a description")
def _refused_ai(context):
    assert context.error and "Only a person accepts a description" in context.error, context.error
    assert sent(context) == []


@when("the editor accepts it as a person")
def _accept_human(context):
    accept_description(context, "human")


@then("the CLI sends one change that marks the description as accepted by that person and does not touch its words")
def _marks(context):
    assert context.error is None, context.error
    patches = [patch for _field, variables in sent(context) for patch in json.loads(variables["patches"])]
    assert len(patches) == 1 and set(patches[0]["expected"]) == {"id", "changeReason", "updatedAt"}, patches
    assert '"descriptionEditedBy":{"actor":"human","name":"Ada Reader"' in patches[0]["expected"]["changeReason"]


@then("the public wiki page for the concept uses the description instead of the factual line")
def _page_uses(context):
    wiki_behaviour("a_description_a_person_accepted")


@when("the editor accepts a concept's description from the CLI")
def _accept_cli(context):
    context.accepted_from_cli = True


@then("the site stamps the acceptance as made through the CLI")
def _stamped(context):
    lambda_behaviour(context, "a person's accept from the CLI is stamped as made through the CLI")


@then("a mark the call claims was made in the Newsroom is stamped as made through the CLI")
def _forged(context):
    lambda_behaviour(context, "a person's accept from the CLI is stamped as made through the CLI")


@then("an earlier mark the call did not change keeps the place it was made")
def _kept(context):
    lambda_behaviour(context, "a person's accept from the CLI is stamped as made through the CLI")


@then('the origin is the CLI only for a token issued to the CLI\'s client, and "signed-in" on a site that has not told its CLI apart')
def _origin(context):
    lambda_behaviour(context, "where a decision was made comes from the token's client")


@when("the wiki sync writes pages for the concepts editors invented")
def _wiki(context):
    context.wiki = True


@then('the page for "Containment" is at "{slug}" and not "{old}"')
def _plain(context, slug, old):
    wiki_behaviour("a_concept_an_editor_invented_gets_a_plain_address")


@then("a page by someone else already at that address is left as it is and the sync says how to resolve it")
def _clash(context):
    wiki_behaviour("a_page_somebody_else_already_has")


@then("an older page with the kind in its address is reported and not moved")
def _older(context):
    wiki_behaviour("an_older_page_for_the_concept")


@when('the editor links "{first}" to "{second}" with the note "{note}"')
def _link(context, first, second, note):
    context.site.calls.clear()
    with mock.patch.object(commands, "select_backend"):
        run(context, lambda flags, **kwargs: signed_in_concepts.knowledge_entities_link(flags, **kwargs), ["--key", first, "--to", second, "--note", note], client=context.client)
    assert context.error is None, context.error


@then("the CLI asks the site for a related-to link between the two concepts with that note")
def _link_sent(context):
    assert sent(context) == [("createConceptLink", {
        "subjectLineageId": "semantic-node-editor_concept--containment", "objectLineageId": "semantic-node-editor_concept--confinement-problem", "note": "Two sides of one fence"})], sent(context)


@then("the site writes one confirmed link whatever order the two are given in, with the note, who wrote it and that it came from the CLI")
def _link_row(context):
    lambda_behaviour(context, "two concepts are linked with related_to")
    lambda_behaviour(context, "the row is the one the Python readers are tested against")


@then("writing the pair again replaces the words and keeps who first wrote them")
def _link_again(context):
    lambda_behaviour(context, "the same pair in the other order is the same link")


@then("a link without words, to itself, to a rejected concept or to a concept that does not exist is refused")
def _link_refused(context):
    lambda_behaviour(context, "a link between concepts without its explanation")


@given("an editor linked two concepts with words, from the CLI")
def _linked(context):
    context.linked = True


def readers(pattern: str) -> None:
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-k", pattern, "src/papyrus_content/concept_link_readers_test.py"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=240,
                          env={**__import__("os").environ, "PYTHONPATH": f"{REPO_ROOT / 'src'}:{REPO_ROOT}"})
    assert done.returncode == 0 and " passed" in done.stdout, done.stdout + done.stderr


@then("a section's context pack lists the link and its words on both concepts")
def _pack(context):
    readers("section_context_pack")


@then("the internal knowledge query indexes the words")
def _query(context):
    readers("internal_knowledge_query")


@then("the knowledge snapshot has a confirmed relation between the two entities and not the words")
def _snapshot(context):
    readers("knowledge_snapshot")


@then("the Cyclotron's link examples and suggestion cuts pass it by")
def _cyclotron(context):
    readers("cyclotron")


@when('the editor links the Reference "{reference}" to the concept "{concept}" with the note "{note}"')
def _ref_concept(context, reference, concept, note):
    context.site.calls.clear()
    run(context, lambda flags, **kwargs: signed_in_concepts.references_link(flags, **kwargs), ["--reference", reference, "--concept", concept, "--note", note], client=context.client)
    assert context.error is None, context.error


@then('the CLI asks the site for a tagged-with link from the Reference to "{name}" with that note')
def _ref_concept_sent(context, name):
    field, variables = sent(context)[-1]
    assert field == "createReferenceLink" and variables["objectKind"] == "semanticNode" and variables["predicate"] == "tagged_with", sent(context)
    assert variables["objectLineageId"] == "semantic-node-editor_concept--confinement-problem" and variables["note"] == "The sibling problem"


@when('the editor links the Reference "{reference}" to the Reference "{other}" as "{predicate}"')
def _ref_ref(context, reference, other, predicate):
    context.site.calls.clear()
    run(context, lambda flags, **kwargs: signed_in_concepts.references_link(flags, **kwargs), ["--reference", reference, "--to-reference", other, "--predicate", predicate], client=context.client)
    assert context.error is None, context.error


@then("the CLI asks the site for a supports link between the two References")
def _ref_ref_sent(context):
    assert sent(context) == [("createReferenceLink", {"subjectLineageId": "ref-1", "objectKind": "reference", "objectLineageId": "ref-2", "predicate": "supports", "note": None})], sent(context)


@when("the editor runs each new command with --dry-run and with --help")
def _dry_and_help(context):
    context.site.calls.clear()
    base = {
        "references link": (signed_in_concepts.references_link, ["--reference", "ref-1", "--to-reference", "ref-2"]),
        "knowledge entities link": (signed_in_concepts.knowledge_entities_link, ["--key", "editor_concept--containment", "--to", "editor_concept--confinement-problem", "--note", "x"]),
    }
    for _name, (function, flags) in base.items():
        run(context, lambda given, function=function, **kwargs: function(given, **kwargs), [*flags, "--dry-run"], client=context.client)
        assert context.error is None, context.error
        run(context, lambda given, function=function, **kwargs: function(given, **kwargs), ["--help"], client=context.client)
        assert context.error is None, context.error
    add_core_concept(context, "Something new", ["--dry-run"])
    with mock.patch.object(section_concepts, "create_authoring_client", return_value=(context.client, None)):
        run(context, lambda flags: section_concepts.sections_concepts(flags), ["add", "--help"])
    with mock.patch.object(commands, "authoring_client", return_value=context.client), mock.patch.object(commands, "select_backend"):
        for command in (commands.knowledge_entities_rename, commands.knowledge_entities_alias):
            run(context, lambda flags, command=command: command(flags), ["--key", "editor_concept--containment", "--name", "Containment", "--add", "boxing", "--actor", "human", "--dry-run"])


@then("the site has been sent nothing")
def _nothing(context):
    assert sent(context) == [], sent(context)
    assert context.section_writes == []


@then("the new routes allow the editor and administrator groups and no other group, and the handler checks the groups again")
def _groups(context):
    lambda_behaviour(context, "the new routes are for the editor and admin groups only")
    lambda_behaviour(context, "the handler checks the editor groups again")


@then("the site's concept and relation models still allow an editor to read and nothing else")
def _models(context):
    done = subprocess.run(["node", "--import", "tsx", "scripts/test-identity-pool-model-access.ts"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stdout + done.stderr
    lambda_behaviour(context, "the data models stay read-only to them")
