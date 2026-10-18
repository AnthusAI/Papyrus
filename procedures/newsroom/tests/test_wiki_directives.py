import unittest

from papyrus_content.markus_renderer.derive import derive_body


class WikiDirectivesTests(unittest.TestCase):
    def test_dynamic_components_survive_into_the_body_ir(self):
        derivation = derive_body(None, "# Wiki\n\n::recent-concepts{limit=5}\n\n::concept-count{kind=\"person\"}\n\nSee [Alpha](concept:alpha).\n")
        self.assertTrue(derivation.ok, [error.message for error in derivation.errors])
        children = derivation.body_ir["document"]["children"]
        names = [child["name"] for child in children if child["type"] == "directive"]
        self.assertEqual(names, ["recent-concepts", "concept-count"])
        self.assertEqual(children[1]["attributes"]["limit"], 5)

    def test_unknown_directives_are_still_rejected(self):
        derivation = derive_body(None, "::no-such-component\n")
        self.assertFalse(derivation.ok)


if __name__ == "__main__":
    unittest.main()
