"""Worker commands honor one checkout configuration, without running a worker."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("configured", [True, False], ids=["explicit-checkout", "default-sibling"])
def test_extraction_and_metadata_use_same_configured_worker(tmp_path, configured):
    """A worktree must not silently run metadata against another checkout."""
    papyrus = tmp_path / "isolated publication"
    checkout = tmp_path / ("custom workers/Biblicus source" if configured else "Biblicus")
    interpreter = checkout / ".venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    env = {**os.environ, "PAPYRUS_ROOT": str(papyrus), "EXPECTED_BIBLICUS": str(checkout)}
    env.pop("BIBLICUS_WORKDIR", None)
    if configured:
        env["BIBLICUS_WORKDIR"] = str(checkout)
    # Fresh imports represent process-start configuration without reloading the
    # shared env module underneath other tests or touching the preview process.
    program = textwrap.dedent("""
        import json, os
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from papyrus_content import reference_url_text as extraction
        from papyrus_newsroom import reference_curation_signals as metadata

        expected = Path(os.environ['EXPECTED_BIBLICUS'])
        assert extraction.BIBLICUS_ROOT == expected
        assert metadata.BIBLICUS_ROOT == expected
        commands = []
        def worker(command, **kwargs):
            commands.append((command, kwargs))
            if command[1] == '-c':
                assert 'from biblicus.url_text import extract_url_text' in command[2]
                return SimpleNamespace(returncode=0, stdout='{"status":"ok","text":"Source text"}', stderr='')
            return SimpleNamespace(returncode=0, stdout='{"task":"title","value":"Title"}', stderr='')
        with patch('subprocess.run', side_effect=worker):
            extraction._run_biblicus_url_text({'source_uri':'https://example.invalid/source'})
            metadata._run_biblicus_summarize_map_reduce(
                output_kind='title', reference={'title':'Source','sourceUri':'https://example.invalid/source'},
                context={'extractedText':'Source text'}, model='offline-model')
        assert len(commands) == 2
        for command, options in commands:
            assert command[0] == str(expected / '.venv/bin/python')
            assert options['cwd'] == expected
            assert options['env']['PYTHONPATH'].split(os.pathsep)[0] == str(expected / 'src')
            assert options['check'] is False
        assert json.loads(commands[1][1]['input'])['extracted_text'] == 'Source text'
    """)
    result = subprocess.run([sys.executable, "-c", program], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_missing_configured_checkout_fails_before_metadata_worker(tmp_path, monkeypatch):
    from papyrus_newsroom import reference_curation_signals as metadata

    missing = tmp_path / "missing worker"
    monkeypatch.setattr(metadata, "BIBLICUS_ROOT", missing)
    def unexpected_worker(*args, **kwargs):
        pytest.fail("Missing checkout must fail before subprocess/provider dispatch")
    monkeypatch.setattr(metadata.subprocess, "run", unexpected_worker)
    with pytest.raises(RuntimeError, match="Biblicus checkout not found"):
        metadata._run_biblicus_summarize_map_reduce(
            output_kind="title", reference={}, context={}, model="offline-model")
