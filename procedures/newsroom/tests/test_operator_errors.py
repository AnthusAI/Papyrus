from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content import env  # noqa: E402
from papyrus_content.operator_errors import (  # noqa: E402
    GraphQLRequestError,
    OperatorError,
    run_with_operator_error_handling,
)


def run_raising(error: BaseException) -> tuple[int, str]:
    def entrypoint() -> int:
        raise error

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        exit_code = run_with_operator_error_handling(entrypoint)
    return exit_code, stderr.getvalue()


class OperatorErrorHandlingTests(unittest.TestCase):
    def test_operator_error_exits_with_its_own_code_and_no_traceback(self) -> None:
        exit_code, stderr = run_raising(OperatorError("bad flag", exit_code=2))
        self.assertEqual(exit_code, 2)
        self.assertEqual(stderr.strip(), "bad flag")

    def test_graphql_request_error_is_operator_facing(self) -> None:
        exit_code, stderr = run_raising(GraphQLRequestError("GraphQL request failed: 401"))
        self.assertEqual(exit_code, 2)
        self.assertNotIn("Traceback", stderr)

    def test_value_error_is_operator_facing(self) -> None:
        exit_code, stderr = run_raising(ValueError("PAPYRUS_X is required."))
        self.assertEqual(exit_code, 2)
        self.assertNotIn("Traceback", stderr)

    def test_unexpected_error_exits_one_with_traceback(self) -> None:
        exit_code, stderr = run_raising(KeyError("boom"))
        self.assertEqual(exit_code, 1)
        self.assertIn("Traceback", stderr)

    def test_successful_entrypoint_returns_its_exit_code(self) -> None:
        self.assertEqual(run_with_operator_error_handling(lambda: 0), 0)


class DotenvPrecedenceTests(unittest.TestCase):
    def test_exported_graphql_endpoint_wins_over_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / ".env").write_text(
                "PAPYRUS_GRAPHQL_ENDPOINT=https://from-dotenv.example/graphql\n", encoding="utf-8"
            )
            with patch.object(env, "PAPYRUS_ROOT", Path(directory)), patch.dict(
                os.environ, {"PAPYRUS_GRAPHQL_ENDPOINT": "https://from-shell.example/graphql"}
            ):
                env.load_dotenv()
                self.assertEqual(os.environ["PAPYRUS_GRAPHQL_ENDPOINT"], "https://from-shell.example/graphql")

    def test_dotenv_fills_unset_variables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / ".env").write_text("PAPYRUS_TEST_ONLY_VARIABLE=from-dotenv\n", encoding="utf-8")
            with patch.object(env, "PAPYRUS_ROOT", Path(directory)), patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PAPYRUS_TEST_ONLY_VARIABLE", None)
                env.load_dotenv()
                self.assertEqual(os.environ["PAPYRUS_TEST_ONLY_VARIABLE"], "from-dotenv")
                os.environ.pop("PAPYRUS_TEST_ONLY_VARIABLE", None)


if __name__ == "__main__":
    unittest.main()
