from __future__ import annotations

import contextlib
import io
import json
import unittest

from papyrus_content.edge_invalidation import (
    MAXIMUM_ATTEMPTS,
    MAXIMUM_PATHS_PER_BATCH,
    WholeSiteInvalidationRefused,
    invalidate_distribution,
)


class FakeThrottle(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class RecordingCloudFront:
    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.calls: list[dict] = []
        self._failures = list(failures or [])

    def create_invalidation(self, **arguments) -> None:
        if self._failures:
            raise self._failures.pop(0)
        self.calls.append(arguments)


def run(paths, client, sleeps=None):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = invalidate_distribution("EDIST", paths, client, sleep=(sleeps.append if sleeps is not None else lambda _s: None))
    return result, output.getvalue()


class EdgeInvalidationTests(unittest.TestCase):
    def test_paths_are_batched_deduplicated_and_counted(self) -> None:
        client = RecordingCloudFront()
        paths = [f"/p/{number}.html" for number in range(MAXIMUM_PATHS_PER_BATCH + 10)] + ["/p/0.html"]
        result, output = run(paths, client)
        self.assertEqual(len(result), MAXIMUM_PATHS_PER_BATCH + 10)
        self.assertEqual([call["InvalidationBatch"]["Paths"]["Quantity"] for call in client.calls], [MAXIMUM_PATHS_PER_BATCH, 10])
        counted = [json.loads(line)["InvalidatedPaths"] for line in output.splitlines()]
        self.assertEqual(counted, [MAXIMUM_PATHS_PER_BATCH, 10])

    def test_non_ascii_paths_are_percent_encoded(self) -> None:
        client = RecordingCloudFront()
        result, _ = run(["/articles/café/"], client)
        self.assertEqual(result, ["/articles/caf%C3%A9/"])

    def test_a_wildcard_is_refused(self) -> None:
        with self.assertRaises(WholeSiteInvalidationRefused):
            run(["/*"], RecordingCloudFront())

    def test_throttling_is_retried_with_growing_delays(self) -> None:
        client = RecordingCloudFront([FakeThrottle("Throttling"), FakeThrottle("TooManyInvalidationsInProgress")])
        sleeps: list[float] = []
        run(["/a"], client, sleeps)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_persistent_throttling_raises_after_the_attempt_limit(self) -> None:
        client = RecordingCloudFront([FakeThrottle("Throttling")] * MAXIMUM_ATTEMPTS)
        with self.assertRaises(FakeThrottle):
            run(["/a"], client)

    def test_other_errors_are_not_retried(self) -> None:
        client = RecordingCloudFront([FakeThrottle("AccessDenied")])
        sleeps: list[float] = []
        with self.assertRaises(FakeThrottle):
            run(["/a"], client, sleeps)
        self.assertEqual(sleeps, [])

    def test_no_paths_makes_no_call(self) -> None:
        client = RecordingCloudFront()
        self.assertEqual(run([], client)[0], [])
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
