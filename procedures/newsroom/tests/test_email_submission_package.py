"""The deployed intake artifact must import without workstation dependencies."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[3]


def test_email_intake_zip_is_reproducible_and_imports_in_lambda(tmp_path):
    spec = importlib.util.spec_from_file_location("email_build", ROOT / "infra/monitoring/build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    assert build.build_email(first) == build.build_email(second)
    extracted = tmp_path / "lambda"
    with zipfile.ZipFile(first) as archive:
        archive.extractall(extracted)
    result = subprocess.run(
        [sys.executable, "-S", "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
         "from papyrus_content.email_submission_intake import handler; assert callable(handler)", str(extracted)],
        cwd=tmp_path, env={"PATH": "/usr/bin:/bin", "PAPYRUS_ROOT": str(extracted)},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
