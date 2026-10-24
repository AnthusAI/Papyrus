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

    def test_the_operator_lane_files_and_moves_a_draft_with_the_same_mutations(self) -> None:
        client = FakeClient({"fileProposal": {"status": "ok", "id": ROW["id"]}}, {"transitionProposal": {"status": "ok", "id": ROW["id"]}})
        with mock.patch.dict("os.environ", {"PAPYRUS_GRAPHQL_AUTH": "iam"}):
            code, output = run(["create", "--kind", "story_draft", "--title", "T", "--body", "b"], client)
            self.assertEqual((code, output.strip()), (0, f"proposals\tcreate\t{ROW['id']}\tdraft"))
            code, output = run(["transition", ROW["id"], "--to", "in_steering"], client)
            self.assertEqual((code, output.strip()), (0, f"proposals\ttransition\t{ROW['id']}\tin_steering"))
        self.assertIn("fileProposal", client.calls[0][0])
        self.assertIn("transitionProposal", client.calls[1][0])

    def test_the_operator_lane_is_told_when_an_editor_decision_is_refused(self) -> None:
        client = FakeClient({"transitionProposal": {"status": "refused", "error": "operator_not_allowed", "message": "An operator can only move a draft to in_steering or declined; the rest is for editors and admins."}})
        with mock.patch.dict("os.environ", {"PAPYRUS_GRAPHQL_AUTH": "iam"}):
            fails(self, ["transition", ROW["id"], "--to", "approved"], client, "operator_not_allowed: An operator can only move a draft")

    def test_the_authoring_client_is_built_for_iam_without_a_user_session(self) -> None:
        with mock.patch.dict("os.environ", {"PAPYRUS_GRAPHQL_AUTH": "iam", "PAPYRUS_GRAPHQL_ENDPOINT": "https://example.appsync-api.eu-west-1.amazonaws.com/graphql"}):
            client, _ = proposals_commands.create_authoring_client()
        self.assertEqual(type(client).__name__, "PapyrusGraphQLAuthoringClient")

    def test_reading_under_iam_says_an_editor_session_is_needed(self) -> None:
        class Denied(FakeClient):
            def graphql(self, query: str, variables: dict | None = None) -> dict:
                raise RuntimeError("Not Authorized to access listProposals on type Query")

        with mock.patch.dict("os.environ", {"PAPYRUS_GRAPHQL_AUTH": "iam"}):
            fails(self, ["list"], Denied(), "needs an editor or admin session")
            fails(self, ["show", ROW["id"]], Denied(), "needs an editor or admin session")
        with mock.patch.dict("os.environ", {"PAPYRUS_GRAPHQL_AUTH": "user"}), mock.patch.object(proposals_commands, "create_authoring_client", return_value=(Denied(), {})), self.assertRaises(RuntimeError):
            proposals_commands.list_command([])

    def test_approve_and_decline_are_transitions_with_an_optional_reason(self) -> None:
        for command, state in (("approve", "approved"), ("decline", "declined")):
            with self.subTest(command=command):
                client = FakeClient({"transitionProposal": {"status": "ok", "id": ROW["id"]}})
                code, output = run([command, ROW["id"], "--reason", "Clear."], client)
                self.assertEqual(client.calls[0][1], {"proposalId": ROW["id"], "state": state, "reason": "Clear.", "result": None})
                self.assertEqual((code, output.strip()), (0, f"proposals\t{command}\t{ROW['id']}\t{state}"))
        fails(self, ["approve"], FakeClient(), "requires a proposal id")

    def test_override_needs_a_result_and_a_public_reason_before_it_asks(self) -> None:
        client = FakeClient({"transitionProposal": {"status": "ok", "id": ROW["id"]}})
        code, output = run(["override", ROW["id"], "--result", "declined", "--reason", "Coordinated votes."], client)
        self.assertEqual(client.calls[0][1], {"proposalId": ROW["id"], "state": "overridden_by_editor", "reason": "Coordinated votes.", "result": "declined"})
        self.assertEqual((code, output.strip()), (0, f"proposals\toverride\t{ROW['id']}\tdeclined"))
        fails(self, ["override", ROW["id"], "--result", "declined"], FakeClient(), "requires --reason: the reason is public")
        fails(self, ["override", ROW["id"], "--reason", "R"], FakeClient(), "--result approved or --result declined")
        refused = FakeClient({"transitionProposal": {"status": "refused", "error": "not_staff", "message": "Only editors."}})
        fails(self, ["override", ROW["id"], "--result", "approved", "--reason", "R"], refused, "not_staff: Only editors")

    def test_pin_unpin_hold_and_release_send_one_edit_each(self) -> None:
        for command in ("pin", "unpin", "hold", "release"):
            with self.subTest(command=command):
                client = FakeClient({"editProposal": {"status": "ok", "id": ROW["id"]}})
                code, output = run([command, ROW["id"]], client)
                self.assertEqual(client.calls[0][1], {"proposalId": ROW["id"], "action": command})
                self.assertEqual((code, output.strip()), (0, f"proposals\t{command}\t{ROW['id']}"))
        refused = FakeClient({"editProposal": {"status": "refused", "error": "operator_not_allowed", "message": "For editors."}})
        fails(self, ["pin", ROW["id"]], refused, "operator_not_allowed: For editors")

    def test_exclude_votes_prints_the_exclusion_id_and_undo_takes_it_back(self) -> None:
        client = FakeClient({"editProposal": {"status": "ok", "id": "exc-0123456789ab"}}, {"editProposal": {"status": "ok", "id": ROW["id"]}})
        code, output = run(["exclude-votes", ROW["id"], "--rule", "new-accounts-24h"], client)
        self.assertEqual(client.calls[0][1], {"proposalId": ROW["id"], "action": "exclude_votes", "rule": "new-accounts-24h"})
        self.assertEqual((code, output.strip()), (0, f"proposals\texclude-votes\t{ROW['id']}\texc-0123456789ab"))
        code, output = run(["undo-exclusion", ROW["id"], "--exclusion", "exc-0123456789ab", "--json"], client)
        self.assertEqual(client.calls[1][1], {"proposalId": ROW["id"], "action": "undo_exclusion", "exclusionId": "exc-0123456789ab"})
        self.assertEqual(json.loads(output)["exclusion"], "exc-0123456789ab")
        fails(self, ["exclude-votes", ROW["id"]], FakeClient(), "requires --rule")
        fails(self, ["undo-exclusion", ROW["id"]], FakeClient(), "requires --exclusion")

    def test_needs_a_look_lists_only_proposals_with_reasons(self) -> None:
        reasons = [{"code": "vote_spike", "label": "Vote spike", "detail": "12 votes in the last hour, against 0 votes in the 23 hours before"}]
        flagged = {**ROW, "id": "prop-" + "c" * 32, "title": "Spiking", "needsLook": json.dumps({"reasons": reasons, "at": "2026-10-22T11:00:00Z"})}
        page = {"listProposals": {"items": [flagged, ROW], "nextToken": None}}
        code, output = run(["needs-a-look"], FakeClient(page))
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), f"{flagged['id']}\tdraft\tSpiking\tVote spike: 12 votes in the last hour, against 0 votes in the 23 hours before")
        _, data = run(["needs-a-look", "--json"], FakeClient(page))
        self.assertEqual([(row["id"], row["reasons"]) for row in json.loads(data)["proposals"]], [(flagged["id"], reasons)])

    def test_show_prints_flags_exclusions_and_reasons(self) -> None:
        row = {**ROW, "pinned": True, "held": False, "exclusions": json.dumps([{"id": "exc-0123456789ab", "rule": "new-accounts-24h", "at": "2026-10-22T10:30:00Z"}]),
               "needsLook": json.dumps({"reasons": [{"code": "new_account_surge", "label": "New-account surge", "detail": "6 of 9 votes"}], "at": "t"})}
        _, output = run(["show", ROW["id"]], FakeClient({"getProposal": row}))
        self.assertIn("flags\tpinned", output)
        self.assertIn("exclusion\texc-0123456789ab\tnew-accounts-24h\t2026-10-22T10:30:00Z\tactive", output)
        self.assertIn("needs-a-look\tnew_account_surge\t6 of 9 votes", output)

    def test_an_unknown_command_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            proposals_commands.proposals_command("delete", [])


if __name__ == "__main__":
    unittest.main()
