"""``papyrus proposals``: what each command sends, what it prints and how it fails."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus import cli as papyrus_cli  # noqa: E402
from papyrus_content import proposals_commands  # noqa: E402

ROW = {"id": "prop-" + "a" * 32, "kind": "merge", "title": "Merge two", "summary": None, "body": "Body.\n", "state": "draft", "proposer": "ai",
       "targets": json.dumps([{"type": "concept", "id": "a"}, {"type": "concept", "id": "b"}]), "evidence": None,
       "history": json.dumps([{"from": None, "to": "draft", "by": "ai", "actor": "s", "reason": None, "at": "2026-10-22T10:00:00Z"}]),
       "communityResult": None, "createdAt": "2026-10-22T10:00:00Z", "updatedAt": "2026-10-22T10:00:00Z"}


class FakeClient:
    def __init__(self, *answers: dict) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, dict]] = []

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        self.calls.append((query, variables or {}))
        return self.answers.pop(0)


def run(argv: list[str], client: FakeClient) -> tuple[int, str]:
    """The exit code and what was printed (an operator error goes to stderr and exits 2, with no traceback)."""
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(proposals_commands, "create_authoring_client", return_value=(client, {})), mock.patch("papyrus_content.cli.load_dotenv"), redirect_stdout(out), redirect_stderr(err):
        code = papyrus_cli.main(["--allow-cross-root", "proposals", *argv])
    return code, out.getvalue() + err.getvalue()


def fails(test: unittest.TestCase, argv: list[str], client: FakeClient, message: str) -> None:
    code, output = run(argv, client)
    test.assertEqual(code, 2, output)
    test.assertRegex(output, message)
    test.assertNotIn("Traceback", output)


class ProposalsCliTests(unittest.TestCase):
    def test_create_sends_the_kind_targets_evidence_and_the_body_file(self) -> None:
        client = FakeClient({"fileProposal": {"status": "ok", "id": ROW["id"]}})
        with tempfile.TemporaryDirectory() as directory:
            body = Path(directory, "body.md")
            body.write_text("# Merge\n\nWhy.\n", encoding="utf-8")
            code, output = run(["create", "--kind", "merge", "--title", "Merge two", "--body-file", str(body), "--target", "concept:a", "--target", "concept:b", "--signals", "9", "--source", "arXiv", "--summary", "One line."], client)
        variables = client.calls[0][1]
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), f"proposals\tcreate\t{ROW['id']}\tdraft")
        self.assertEqual((variables["kind"], variables["title"], variables["body"], variables["summary"]), ("merge", "Merge two", "# Merge\n\nWhy.\n", "One line."))
        self.assertEqual(json.loads(variables["targets"]), [{"type": "concept", "id": "a"}, {"type": "concept", "id": "b"}])
        self.assertEqual(json.loads(variables["evidence"]), {"signals": 9, "source": "arXiv"})

    def test_a_refusal_reads_as_an_error_with_the_reason(self) -> None:
        client = FakeClient({"fileProposal": {"status": "refused", "error": "invalid_targets", "message": "A merge proposal names 2 to 10 target(s)."}})
        fails(self, ["create", "--kind", "merge", "--title", "T", "--body", "b"], client, "invalid_targets: A merge proposal names")

    def test_create_needs_a_kind_a_title_and_a_body_and_a_well_formed_target(self) -> None:
        for argv, message in (
            (["create", "--title", "T", "--body", "b"], "requires --kind and --title"),
            (["create", "--kind", "merge", "--title", "T"], "requires --body"),
            (["create", "--kind", "merge", "--title", "T", "--body", "b", "--target", "nonsense"], "TYPE:ID"),
        ):
            with self.subTest(argv=argv):
                fails(self, argv, FakeClient(), message)

    def test_transition_sends_the_state_reason_and_result(self) -> None:
        client = FakeClient({"transitionProposal": {"status": "ok", "id": ROW["id"]}})
        code, output = run(["transition", ROW["id"], "--to", "overridden_by_editor", "--reason", "Coordinated votes.", "--result", "declined"], client)
        self.assertEqual(client.calls[0][1], {"proposalId": ROW["id"], "state": "overridden_by_editor", "reason": "Coordinated votes.", "result": "declined"})
        self.assertEqual((code, output.strip()), (0, f"proposals\ttransition\t{ROW['id']}\toverridden_by_editor"))

    def test_a_refused_transition_names_the_rule(self) -> None:
        client = FakeClient({"transitionProposal": {"status": "refused", "error": "reason_required", "message": "Overriding the community needs a public reason."}})
        fails(self, ["transition", ROW["id"], "--to", "overridden_by_editor"], client, "reason_required: Overriding")

    def test_list_prints_newest_first_and_filters_by_state(self) -> None:
        older = {**ROW, "id": "prop-" + "b" * 32, "state": "in_steering", "title": "Older", "createdAt": "2026-10-21T10:00:00Z"}
        client = FakeClient({"listProposals": {"items": [older, ROW], "nextToken": None}}, {"listProposals": {"items": [older, ROW], "nextToken": None}})
        _, output = run(["list"], client)
        self.assertEqual([line.split("\t")[1] for line in output.strip().splitlines()], ["draft", "in_steering"])
        _, filtered = run(["list", "--state", "in_steering", "--json"], client)
        self.assertEqual([row["id"] for row in json.loads(filtered)["proposals"]], [older["id"]])

    def test_show_prints_targets_history_and_the_body(self) -> None:
        _, output = run(["show", ROW["id"]], FakeClient({"getProposal": ROW}))
        self.assertIn("target\tconcept\ta", output)
        self.assertIn("history\t2026-10-22T10:00:00Z\t- -> draft", output)
        self.assertTrue(output.rstrip().endswith("Body."))
        fails(self, ["show", "prop-missing"], FakeClient({"getProposal": None}), "not found")

    def test_publish_runs_the_reader_snapshot(self) -> None:
        with mock.patch("papyrus_content.projection_trigger.trigger_projection", return_value={"ok": True, "scheduled": "reader-snapshot", "via": "content-actions"}) as trigger:
            code, output = run(["publish"], FakeClient())
        trigger.assert_called_once_with({"task": "reader-snapshot"})
        self.assertEqual((code, output.strip()), (0, "proposals\tpublish\treader-snapshot\tcontent-actions"))
        with mock.patch("papyrus_content.projection_trigger.trigger_projection", return_value={"ok": False, "error": "boom"}):
            fails(self, ["publish"], FakeClient(), "Could not start the snapshot: boom")

    def test_an_unknown_command_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            proposals_commands.proposals_command("delete", [])


if __name__ == "__main__":
    unittest.main()
