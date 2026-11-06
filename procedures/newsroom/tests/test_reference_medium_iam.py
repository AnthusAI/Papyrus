"""The workers that write a Reference's medium, evidence level, playlist address, medium key and outbound links already hold every GraphQL operation that needs.

IAM on the data API is per operation (``types/Query/fields/...``, ``types/Mutation/fields/...``); the Reference's own attributes are plain attributes
with no resolver, so a new attribute needs no grant. What a writer needs is the mutation that carries it. The router writes through
``createReference`` / ``updateReference`` (intake, votes) and ``createReferenceAttachment`` plus the attachment upload pair (the stored links); the
research worker writes the same. Nothing in either role reads References by medium: only the signed-in newsroom and the snapshot task do, and they do
not use these roles. This test fails if a publication's grant ever loses one of them.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

TEMPLATE = Path(__file__).resolve().parents[3] / "infra" / "monitoring" / "papyrus-monitoring.yaml"
NEEDED = {"getReference", "createReference", "updateReference", "createReferenceAttachment", "createModelAttachmentUpload", "completeModelAttachmentUpload"}
PUBLICATION_APIS = ("AnthUsApiId", "PapyrusApiId", "ThreatIntelApiId", "DataParadeApiId", "PilobolusApiId", "ShippedApiId", "DistinctiveApiId", "MachinesOnMachinesApiId")


class Loader(yaml.SafeLoader):
    pass


Loader.add_multi_constructor("!", lambda loader, suffix, node: {
    "Fn::" + suffix if suffix != "Ref" else "Ref":
        loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode)
        else loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node)})


@pytest.fixture(scope="module")
def resources():
    return yaml.load(TEMPLATE.read_text(), Loader=Loader)["Resources"]


def grants(resources, role: str) -> dict[str, set[str]]:
    """``{api: {operation, ...}}`` the role holds, from its inline policies and every managed policy attached to it."""
    names = [role] + [name for name, resource in resources.items() if resource["Type"] == "AWS::IAM::ManagedPolicy"
                      and any(entry == {"Ref": role} for entry in resource["Properties"].get("Roles", []))]
    found: dict[str, set[str]] = {}
    for name in names:
        properties = resources[name]["Properties"]
        statements = [statement for policy in properties.get("Policies", []) for statement in policy["PolicyDocument"]["Statement"]] \
            if resources[name]["Type"] == "AWS::IAM::Role" else properties["PolicyDocument"]["Statement"]
        for statement in statements:
            if statement.get("Action") != "appsync:GraphQL":
                continue
            for resource in statement["Resource"]:
                text = resource["Fn::Sub"] if isinstance(resource, dict) else resource
                match = re.search(r"apis/([^/]+)/types/\w+/fields/(\w+)", text)
                api = match.group(1).strip("${}") if match.group(1).startswith("$") else match.group(1)
                found.setdefault(api, set()).add(match.group(2))
    return found


@pytest.mark.parametrize("api", PUBLICATION_APIS)
def test_the_router_can_write_a_reference_its_medium_key_and_its_links_in_every_publication(resources, api):
    assert NEEDED <= grants(resources, "RouterRole")[api]


def test_the_research_worker_can_write_them_in_every_publication(resources):
    assert NEEDED <= grants(resources, "ResearchWorkerRole")["*"]


def test_no_worker_role_reads_the_medium_index():
    template = TEMPLATE.read_text()
    assert "listReferencesByMediumFeedAndArrival" not in template, "grant it to the role that reads it, and say which in docs/reference-feed-indexes.md"


def test_no_worker_role_reads_the_content_needed_index_or_calls_the_capture_action():
    """The transcript worker is a signed-in person's command (PPY-d294d8): it reads the index and calls ``correctReferenceCapture`` as the user, through
    the data API's own group authorization. No monitoring role holds either operation, and the new ``captureReason`` and ``contentNeededKey`` attributes
    need no grant (they ride on ``createReference`` / ``updateReference``, which the router already holds)."""
    template = TEMPLATE.read_text()
    assert "listReferencesByContentNeededAndArrival" not in template and "correctReferenceCapture" not in template


def test_the_public_blocks_attributes_need_no_grant_and_no_worker_role_reads_their_index():
    """``publicFeedKey``, ``publicOrderKey``, ``cardImage``, ``cardSummary``, ``cardSiteName`` and ``cardPageTitle`` (PPY-7f1e54) are plain attributes with no resolver, so they
    ride on ``createReference`` / ``updateReference``, which the router and the research worker already hold in every publication (``NEEDED`` above). The
    preview writer (``reference_images.attach_preview``) also needs the attachment operations it already has. The index that reads them is read by the site's
    own projection task, not by a monitoring role, so the template names none of them and no new grant is needed."""
    template = TEMPLATE.read_text()
    for name in ("publicFeedKey", "publicOrderKey", "cardImage", "cardSummary", "cardSiteName", "cardPageTitle", "listReferencesByPublicFeed"):
        assert name not in template, name
