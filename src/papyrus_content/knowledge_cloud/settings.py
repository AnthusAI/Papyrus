"""The settings a site commits for its knowledge run: ``vocabulary.yml``, ``stop-words.txt`` and ``review-guidance.md``.

They live in the repository beside the site's ``infra/site.json`` (``knowledgeRun.settingsDirectory``). The job stack zips that directory
into a deploy-time asset and names it in ``KNOWLEDGE_SETTINGS_ARCHIVE``; every stage unpacks it into ``config/`` of its work directory
and says in the task log where each file came from. The run state in S3 holds none of this and is never consulted for it, so a stale copy
there cannot override what was reviewed and deployed. A site that commits nothing gets the generic vocabulary
(``defaults.py``) and no stop words or review guidance. Docs: docs/knowledge-cloud-run.md.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from pathlib import Path

from .config import CloudRunConfig
from .defaults import VOCABULARY_FILE, default_vocabulary

STOP_WORDS_FILE = "stop-words.txt"
REVIEW_GUIDANCE_FILE = "review-guidance.md"
#: The files a site may commit; the stack refuses any other name, and so does the task.
SETTINGS_FILES = (VOCABULARY_FILE, STOP_WORDS_FILE, REVIEW_GUIDANCE_FILE)


class SettingsError(RuntimeError):
    pass


def split_archive(address: str) -> tuple[str, str]:
    scheme, _, rest = address.partition("://")
    bucket, _, key = rest.partition("/")
    if scheme != "s3" or not bucket or not key:
        raise SettingsError(f"KNOWLEDGE_SETTINGS_ARCHIVE must be s3://<bucket>/<key>, got {address!r}")
    return bucket, key


def load_settings(config: CloudRunConfig, directory: Path, read_object: Callable[[str, str], bytes | None]) -> dict[str, str]:
    """Write the site's settings into ``directory`` and return where each file came from (also printed, one line per file)."""
    directory.mkdir(parents=True, exist_ok=True)
    committed: dict[str, bytes] = {}
    if config.settings_archive:
        bucket, key = split_archive(config.settings_archive)
        body = read_object(bucket, key)
        if body is None:
            raise SettingsError(f"the committed settings {config.settings_archive} are not there; deploy the job stack again")
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            for name in archive.namelist():
                if name not in SETTINGS_FILES:
                    raise SettingsError(f"the committed settings hold {name!r}, which is not a settings file (known: {', '.join(SETTINGS_FILES)})")
                committed[name] = archive.read(name)
    sources: dict[str, str] = {}
    for name in SETTINGS_FILES:
        if name in committed:
            (directory / name).write_bytes(committed[name])
            sources[name] = "committed settings"
        elif name == VOCABULARY_FILE:
            (directory / name).write_text(default_vocabulary(config.publication))
            sources[name] = "generic default"
        else:
            (directory / name).unlink(missing_ok=True)
            sources[name] = "none"
        print(f"config/{name}: {sources[name]}", flush=True)
    return sources
