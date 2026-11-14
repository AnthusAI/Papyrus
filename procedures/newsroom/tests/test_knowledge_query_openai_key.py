import os
import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_knowledge_query import services  # noqa: E402

BRANCH = "/amplify/app1/branch-hash/OPENAI_API_KEY"
SHARED = "/amplify/shared/app1/OPENAI_API_KEY"
CONFIG = '{"OPENAI_API_KEY": {"path": "%s", "sharedPath": "%s"}}' % (BRANCH, SHARED)
PLACEHOLDER_VALUE = "stub-value-not-a-secret"


class StubSsmError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class StubSsm:
    def __init__(self, store, errors=None):
        self.store = store
        self.errors = errors or {}
        self.calls = []

    def get_parameter(self, Name, WithDecryption):
        self.calls.append(Name)
        if Name in self.errors:
            raise StubSsmError(self.errors[Name])
        if Name not in self.store:
            raise StubSsmError("ParameterNotFound")
        return {"Parameter": {"Value": self.store[Name]}}


def resolve(ssm, config=CONFIG):
    boto3 = mock.Mock()
    boto3.client.return_value = ssm
    env = {"AMPLIFY_SSM_ENV_CONFIG": config, "OPENAI_API_KEY": ""}
    with mock.patch.dict(os.environ, env), mock.patch.dict(sys.modules, {"boto3": boto3}):
        services._cached_openai_api_key = ""
        try:
            return services._resolve_openai_api_key()
        finally:
            services._cached_openai_api_key = ""


class OpenAiKeyLoaderTests(unittest.TestCase):
    def test_branch_path_wins_when_present(self):
        ssm = StubSsm({BRANCH: PLACEHOLDER_VALUE, SHARED: "other"})
        self.assertEqual(resolve(ssm), PLACEHOLDER_VALUE)
        self.assertEqual(ssm.calls, [BRANCH])

    def test_shared_path_used_when_branch_path_missing(self):
        ssm = StubSsm({SHARED: PLACEHOLDER_VALUE})
        self.assertEqual(resolve(ssm), PLACEHOLDER_VALUE)
        self.assertEqual(ssm.calls, [BRANCH, SHARED])

    def test_access_denied_on_branch_path_is_not_swallowed(self):
        ssm = StubSsm({SHARED: PLACEHOLDER_VALUE}, errors={BRANCH: "AccessDeniedException"})
        with self.assertRaises(StubSsmError):
            resolve(ssm)
        self.assertEqual(ssm.calls, [BRANCH])

    def test_throttling_on_shared_path_is_not_swallowed(self):
        ssm = StubSsm({}, errors={SHARED: "ThrottlingException"})
        with self.assertRaises(StubSsmError):
            resolve(ssm)

    def test_neither_path_found_fails_clearly_without_a_value(self):
        with self.assertRaises(RuntimeError) as caught:
            resolve(StubSsm({}))
        self.assertIn(BRANCH, str(caught.exception))
        self.assertIn(SHARED, str(caught.exception))

    def test_identical_paths_are_read_once(self):
        ssm = StubSsm({})
        config = '{"OPENAI_API_KEY": {"path": "%s", "sharedPath": "%s"}}' % (SHARED, SHARED)
        with self.assertRaises(RuntimeError):
            resolve(ssm, config)
        self.assertEqual(ssm.calls, [SHARED])

    def test_key_is_cached_after_first_load(self):
        ssm = StubSsm({SHARED: PLACEHOLDER_VALUE})
        boto3 = mock.Mock()
        boto3.client.return_value = ssm
        env = {"AMPLIFY_SSM_ENV_CONFIG": CONFIG, "OPENAI_API_KEY": ""}
        with mock.patch.dict(os.environ, env), mock.patch.dict(sys.modules, {"boto3": boto3}):
            services._cached_openai_api_key = ""
            try:
                services._resolve_openai_api_key()
                services._resolve_openai_api_key()
            finally:
                services._cached_openai_api_key = ""
        self.assertEqual(ssm.calls, [BRANCH, SHARED])


if __name__ == "__main__":
    unittest.main()
