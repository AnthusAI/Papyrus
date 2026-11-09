"""The topic engine: documents in, topics out, behind a small interface.

``TopicEngine.model`` takes plain documents (an id and some text) and returns the topics it found, each with its top terms and the ids of the
documents in it. A document in no topic is simply not listed. The interface holds nothing but data on both sides, so a later cloud job can run
the same call somewhere else and store the same answer (the job itself is not built; PPY-d0f028 follow-up). Tests use ``fakes.FakeTopicEngine``.

``BiblicusTopicEngine`` is the engine the weekly knowledge run uses (docs/knowledge-cloud-run.md): BERTopic through Biblicus, with the same
settings (``knowledge_snapshot/topic_config.py``). Biblicus takes its input as a corpus on disk, so the engine writes a throwaway corpus of one
Markdown file per document, extracts its text and runs ``biblicus analyze topics``, all through the one process boundary
(``biblicus_runner.BiblicusRunner``). Nothing is kept: the corpus is deleted when the call returns.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

import yaml

from papyrus_content.ids import deterministic_uuid

LABEL_TERMS = 3
MIN_TEXT_CHARACTERS = 20    # a title alone is a document


@dataclass(frozen=True)
class TopicDocument:
    id: str
    text: str


@dataclass(frozen=True)
class FoundTopic:
    terms: tuple[str, ...]            # best first
    member_ids: tuple[str, ...]       # ids of the documents in the topic

    @property
    def label(self) -> str:
        return ", ".join(self.terms[:LABEL_TERMS])


class TopicEngineError(RuntimeError):
    """The engine could not run or its answer could not be read."""


class TopicEngine(Protocol):
    name: str      # recorded with a result and part of its cache key, with `version`
    version: str

    def model(self, documents: Sequence[TopicDocument], *, min_cluster_size: int) -> list[FoundTopic]:
        """Topics of at least ``min_cluster_size`` documents. Raises ``TopicEngineError`` when the engine cannot run."""
        ...


def configuration(min_cluster_size: int) -> dict:
    """The knowledge run's BERTopic settings with the cluster size of this call."""
    from papyrus_content.knowledge_snapshot.topic_config import topic_modeling_configuration

    config = topic_modeling_configuration()
    config["text_source"]["min_text_characters"] = MIN_TEXT_CHARACTERS
    config["bertopic_analysis"]["parameters"]["min_topic_size"] = min_cluster_size
    hdbscan = config["bertopic_analysis"]["hdbscan_model"]["parameters"]
    hdbscan["min_cluster_size"] = min_cluster_size
    hdbscan["min_samples"] = min(hdbscan["min_samples"], min_cluster_size)
    return config


def corpus_file(document: TopicDocument) -> str:
    """One document as the Markdown file Biblicus ingests: its id (as the UUID Biblicus keeps) in the front matter, then the text."""
    front = yaml.safe_dump({"biblicus": {"id": deterministic_uuid(document.id)}, "papyrus_topic_document": document.id}, sort_keys=False)
    return f"---\n{front}---\n\n{document.text.strip()}\n"


class BiblicusTopicEngine:
    name = "biblicus-bertopic"

    def __init__(self, runner: Any | None = None, *, timeout_seconds: float | None = None) -> None:
        self._runner = runner
        self.timeout_seconds = timeout_seconds
        self.version = self._biblicus_version()

    @staticmethod
    def _biblicus_version() -> str:
        try:
            from importlib.metadata import version

            return version("biblicus")
        except Exception:   # not installed here: the call will say so
            return "unknown"

    def _make_runner(self, workdir: Path) -> Any:
        from papyrus_content.biblicus_runner import BiblicusExecutableError, BiblicusRunner, build_biblicus_environment, resolve_biblicus_executable

        try:
            return BiblicusRunner(workdir=workdir, environment=build_biblicus_environment(), executable=resolve_biblicus_executable())
        except BiblicusExecutableError as error:
            raise TopicEngineError(str(error)) from error

    def model(self, documents: Sequence[TopicDocument], *, min_cluster_size: int) -> list[FoundTopic]:
        if len(documents) < 2 * min_cluster_size:
            return []   # too few documents for a cluster of that size; the caller reports it
        with tempfile.TemporaryDirectory(prefix="papyrus-topics-") as scratch:
            root = Path(scratch)
            corpus = root / "corpus"
            runner = self._runner or self._make_runner(root)
            files = corpus / "raw" / "papyrus"
            try:
                runner.run(["init", str(corpus)])
                files.mkdir(parents=True, exist_ok=True)
                for index, document in enumerate(documents):
                    (files / f"{index}.md").write_text(corpus_file(document), encoding="utf-8")
                runner.run(["reindex", "--corpus", str(corpus)])
                runner.run(["extract", "build", "--corpus", str(corpus), "--stage", "pass-through-text"])
                snapshot = json.loads((corpus / "extracted" / "pipeline" / "latest.json").read_text(encoding="utf-8"))["snapshot_id"]
                settings = root / "topic-modeling.yml"
                settings.write_text(yaml.safe_dump(configuration(min_cluster_size), sort_keys=False, default_flow_style=None, width=100), encoding="utf-8")
                output = runner.run(["analyze", "topics", "--corpus", str(corpus), "--configuration", str(settings),
                                     "--extraction-snapshot", f"pipeline:{snapshot}"], timeout_seconds=self.timeout_seconds)
            except TopicEngineError:
                raise
            except Exception as error:   # the runner's typed errors, a missing file: one plain failure for the caller
                raise TopicEngineError(f"Topic modeling failed: {error}") from error
        return self._topics(output.stdout, documents)

    @staticmethod
    def _topics(stdout: str, documents: Sequence[TopicDocument]) -> list[FoundTopic]:
        try:
            report = json.loads(stdout)["report"]
        except (ValueError, KeyError, TypeError) as error:
            raise TopicEngineError(f"Topic modeling printed an answer that could not be read: {error}") from error
        if report.get("errors"):
            raise TopicEngineError("Topic modeling reported: " + "; ".join(str(entry) for entry in report["errors"]))
        original = {deterministic_uuid(document.id): document.id for document in documents}
        found = []
        for topic in report.get("topics") or []:
            if int(topic.get("topic_id", 0)) < 0:
                continue   # BERTopic's outlier group is not a topic
            terms = tuple(entry["keyword"] for entry in sorted(topic.get("keywords") or [], key=lambda entry: -entry["score"]))
            members = tuple(original[identifier] for identifier in topic.get("document_ids") or [] if identifier in original)
            if members:
                found.append(FoundTopic(terms=terms, member_ids=members))
        return found
