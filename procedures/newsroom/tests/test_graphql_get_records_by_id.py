import unittest
from unittest import mock

from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient


class GraphQLGetRecordsByIdTests(unittest.TestCase):
    def test_uses_batched_point_lookups_never_the_whole_table(self):
        client = PapyrusGraphQLAuthoringClient.__new__(PapyrusGraphQLAuthoringClient)
        with mock.patch.object(client, "get_many") as get_many, mock.patch.object(
            client, "list_records"
        ) as list_records:
            get_many.side_effect = lambda model, ids: {record_id: {"id": record_id, "model": model} for record_id in ids}
            resolved = client.get_records_by_id("Reference", ["ref-a", "ref-b"])
            many = client.get_records_by_id("Reference", [f"ref-{n}" for n in range(500)])
        self.assertEqual(
            resolved,
            {
                "ref-a": {"id": "ref-a", "model": "Reference"},
                "ref-b": {"id": "ref-b", "model": "Reference"},
            },
        )
        self.assertEqual(len(many), 500)   # the fallback that read the whole table above 100 ids is gone
        list_records.assert_not_called()


if __name__ == "__main__":
    unittest.main()
