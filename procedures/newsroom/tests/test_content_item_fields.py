import unittest

from papyrus_content.graphql_authoring import ITEM_FIELDS, PUBLISHED_ITEM_FIELDS
from papyrus_content.model_attachments import expand_private_payload_records

NEW_FIELDS = ("bodyMarkus", "bodyIr", "aliases", "metadata")


class ContentItemFieldsTest(unittest.TestCase):
    def test_field_lists_select_new_fields(self):
        for fields in (ITEM_FIELDS, PUBLISHED_ITEM_FIELDS):
            selected = fields.split()
            for name in NEW_FIELDS:
                self.assertIn(name, selected)

    def test_expand_private_payload_records_keeps_new_fields_inline(self):
        for model_name in ("Item", "PublishedItem"):
            record = {
                "modelName": model_name,
                "expected": {
                    "id": "item-1",
                    "slug": "a",
                    "bodyMarkus": "x",
                    "bodyIr": "{}",
                    "aliases": ["/blog/old"],
                    "metadata": "{}",
                },
            }
            expanded = expand_private_payload_records([record])
            self.assertEqual(len(expanded), 1)
            expected = expanded[0]["expected"]
            self.assertEqual(expected["bodyMarkus"], "x")
            self.assertEqual(expected["bodyIr"], "{}")
            self.assertEqual(expected["aliases"], ["/blog/old"])
            self.assertEqual(expected["metadata"], "{}")


if __name__ == "__main__":
    unittest.main()
