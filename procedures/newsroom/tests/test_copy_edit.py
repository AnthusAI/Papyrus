from __future__ import annotations

import unittest

from papyrus_content.copy_edit import apply_fixes, mechanical_fixes


def utf16(text: str, index: int) -> int:
    return len(text[:index].encode("utf-16-le")) // 2


def finding(body: str, excerpt: str, replacement, *, lane="rules", status="violation", occurrence=0, policy="p") -> dict:
    start = -1
    for _ in range(occurrence + 1):
        start = body.index(excerpt, start + 1)
    out = {"id": f"{policy}-{start}", "policyId": policy, "lane": lane, "status": status, "excerpt": excerpt,
           "span": {"start": utf16(body, start), "end": utf16(body, start + len(excerpt))}}
    if replacement is not None:
        out["replacement"] = replacement
    return out


class MechanicalFixTests(unittest.TestCase):
    def test_only_rules_violations_with_a_declared_replacement_are_mechanical(self):
        body = "Plexus is vague and Plexus again."
        findings = [
            finding(body, "Plexus", "Primus"),
            finding(body, "vague", None),
            finding(body, "Plexus", "Primus", occurrence=1, lane="classifier"),
            finding(body, "again", "afresh", status="review"),
        ]
        edits = mechanical_fixes(body, findings)
        self.assertEqual([(e["from"], e["to"]) for e in edits], [("Plexus", "Primus")])
        self.assertEqual(apply_fixes(body, edits), "Primus is vague and Plexus again.")

    def test_spans_are_utf16_so_text_after_an_emoji_is_still_found(self):
        body = "Hi \U0001F600 do not stop."
        edits = mechanical_fixes(body, [finding(body, "do not", "don't")])
        self.assertEqual(apply_fixes(body, edits), "Hi \U0001F600 don't stop.")

    def test_overlaps_keep_the_first_and_a_moved_excerpt_is_skipped(self):
        body = "do not do that"
        first, overlapping = finding(body, "do not", "don't"), finding(body, "not do", "nope", policy="q")
        self.assertEqual(len(mechanical_fixes(body, [overlapping, first])), 1)
        stale = finding(body, "do not", "don't")
        self.assertEqual(mechanical_fixes("do NOT do that", [stale]), [])

    def test_a_replacement_equal_to_the_text_changes_nothing(self):
        body = "same"
        self.assertEqual(mechanical_fixes(body, [finding(body, "same", "same")]), [])

    def test_several_edits_apply_without_shifting_each_other(self):
        body = "A do not B do not C"
        findings = [finding(body, "do not", "don't"), finding(body, "do not", "don't", occurrence=1)]
        self.assertEqual(apply_fixes(body, mechanical_fixes(body, findings)), "A don't B don't C")


if __name__ == "__main__":
    unittest.main()
