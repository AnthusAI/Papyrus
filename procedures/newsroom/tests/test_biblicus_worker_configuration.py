"""Worker commands honor one BIBLICUS_WORKDIR configuration, without running a worker."""
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from biblicus_runner_support import completed, fake_biblicus_subprocess

URL_TEXT_OUTPUT = json.dumps({
    "status": "ok", "source_kind": "web", "strategy": "direct", "text": "Source text", "markdown": "Source text",
    "title": None, "content_type": None, "prompt_version": "v1", "attempts": [], "error": None,
})
TITLE_OUTPUT = json.dumps({"status": "ok", "task": "title", "value": "Title"})


def test_extraction_and_metadata_use_same_configured_workdir(tmp_path):
    """Both bridges run the console script in the workdir named by BIBLICUS_WORKDIR."""
    papyrus = tmp_path / "isolated publication"
    workdir = tmp_path / "custom workers/Biblicus workdir"
    workdir.mkdir(parents=True)
    env = {**os.environ, "PAPYRUS_ROOT": str(papyrus), "EXPECTED_WORKDIR": str(workdir.resolve()), "BIBLICUS_WORKDIR": str(workdir)}
    program = textwrap.dedent("""
        import json, os
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from papyrus_content import biblicus_runner
        from papyrus_content import reference_url_text as extraction
        from papyrus_newsroom import reference_curation_signals as metadata

        expected = Path(os.environ['EXPECTED_WORKDIR'])
        console_script = expected / 'biblicus'
        commands = []
        def worker(command, **kwargs):
            commands.append((command, kwargs))
            if command[1:3] == ['extract', 'url-text']:
                return SimpleNamespace(returncode=0, stdout=os.environ['URL_TEXT_OUTPUT'], stderr='')
            return SimpleNamespace(returncode=0, stdout=os.environ['TITLE_OUTPUT'], stderr='')
        with patch.object(biblicus_runner, 'resolve_biblicus_executable', return_value=console_script), \
                patch('subprocess.run', side_effect=worker):
            extraction._run_biblicus_url_text({'source_uri': 'https://example.invalid/source'})
            metadata._run_biblicus_summarize_map_reduce(
                output_kind='title', reference={'title': 'Source', 'sourceUri': 'https://example.invalid/source'},
                context={'extractedText': 'Source text'}, model='offline-model')
        assert len(commands) == 2
        for command, options in commands:
            assert command[0] == str(console_script)
            assert options['cwd'] == expected
            assert options['env']['BIBLICUS_WORKDIR'] == str(expected)
            assert options['check'] is False
        assert commands[0][0][1:] == ['extract', 'url-text', '--input-json', '-', '--format', 'json']
        assert commands[1][0][1:5] == ['summarize', 'map-reduce', '--task', 'title']
        assert json.loads(commands[1][1]['input'])['extracted_text'] == 'Source text'
    """)
    env.update(URL_TEXT_OUTPUT=URL_TEXT_OUTPUT, TITLE_OUTPUT=TITLE_OUTPUT)
    result = subprocess.run([sys.executable, "-c", program], env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr


def test_missing_workdir_fails_before_metadata_worker(tmp_path, monkeypatch):
    from papyrus_content.biblicus_runner import BiblicusWorkdirError
    from papyrus_newsroom import reference_curation_signals as metadata

    monkeypatch.setenv("BIBLICUS_WORKDIR", str(tmp_path / "missing worker"))
    def unexpected_worker(*args, **kwargs):
        pytest.fail("Missing workdir must fail before subprocess/provider dispatch")
    monkeypatch.setattr(subprocess, "run", unexpected_worker)
    with pytest.raises(BiblicusWorkdirError, match="does not exist"):
        metadata._run_biblicus_summarize_map_reduce(
            output_kind="title", reference={}, context={"extractedText": "Source text"}, model="offline-model")


def test_unset_workdir_fails_with_the_environment_variable_name(monkeypatch):
    from papyrus_content.biblicus_runner import BiblicusWorkdirError
    from papyrus_newsroom import reference_curation_signals as metadata

    monkeypatch.delenv("BIBLICUS_WORKDIR", raising=False)
    with pytest.raises(BiblicusWorkdirError, match="BIBLICUS_WORKDIR is required"):
        metadata._run_biblicus_summarize_map_reduce(
            output_kind="title", reference={}, context={"extractedText": "Source text"}, model="offline-model")


def test_metadata_source_context_is_unknown_without_explicit_source_evidence(monkeypatch, tmp_path):
    from papyrus_newsroom import reference_curation_signals as metadata

    captured = []
    def worker(command, **kwargs):
        captured.append(json.loads(kwargs['input']))
        return completed(stdout=TITLE_OUTPUT)
    fake_biblicus_subprocess(monkeypatch, tmp_path, worker)
    metadata._run_biblicus_summarize_map_reduce(output_kind='title', reference={
        'sourceUri': 'https://example.invalid/2021/01/07/incident', 'importedAt': '2026-10-15T00:00:00Z',
        'curationStatus': 'archived'}, context={'extractedText': 'Source text'}, model='offline-model')
    assert captured[0]['source_publication_date'] is None
    assert captured[0]['source_is_archived'] is None
    assert captured[0]['generated_title'] == ''
