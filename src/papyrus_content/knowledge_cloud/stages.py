"""The stages of the cloud knowledge run: the workstation runbook (docs/knowledge-workstation-run.md) as container tasks.

Each stage downloads the state it needs from S3, runs the same commands an operator would, uploads what changed and
records itself in the run ledger. Stages are idempotent. The stage list ends with ``projection``; the state machine
never reaches it after a failure, and ``projection`` never passes ``--allow-deletions``.
"""

from __future__ import annotations

import datetime as dt
import importlib.metadata
import json
import re
import subprocess
import sys
import time
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import cost as costs
from .config import PROJECTION_STAGE, STAGES, CloudRunConfig
from .defaults import OUTPUTS_FILE, VOCABULARY_FILE, default_outputs, default_vocabulary
from .ledger import SUCCEEDED, RunLedger
from .state import StateStore

IDENTITY_THRESHOLD = "0.5"
TREND_WEEKS = "26"
ENTITY_HREF = "/wiki/{slug}/"
DELETION_FLAG = "--allow-deletions"
ARCHIVE_DIRECTORY = "_data/knowledge/history"
RETIRED_FILE = "retired-wiki-items.json"
FORBIDDEN_FLAGS = (DELETION_FLAG, "--reconcile", "--replace")  # a run only writes: no cleanup, no replacing an archived week


class StageFailed(RuntimeError):
    pass


Shell = Callable[..., None]


def run_shell(args: list[str], *, cwd: Path, env: Mapping[str, str], stdout: Path | None = None) -> None:
    """Run a command, streaming its output to the task log (stdout goes to a file when asked); raise on failure."""
    printable = " ".join(args)
    print(f"+ {printable}", flush=True)
    if stdout is not None:
        stdout.parent.mkdir(parents=True, exist_ok=True)
        with stdout.open("wb") as handle:
            result = subprocess.run(args, cwd=cwd, env=dict(env), stdout=handle, stderr=sys.stderr, check=False)
    else:
        result = subprocess.run(args, cwd=cwd, env=dict(env), check=False)
    if result.returncode != 0:
        if stdout is not None:  # a command that fails on stdout (Biblicus's failure envelope) would otherwise leave no reason in the task log
            print(f"{args[0]} failed; its standard output:\n{stdout.read_text(errors='replace')[-4000:]}", file=sys.stderr, flush=True)
        raise StageFailed(f"`{args[0]} {args[1] if len(args) > 1 else ''}` exited with {result.returncode}")


@dataclass
class Run:
    config: CloudRunConfig
    state: StateStore
    ledger: RunLedger
    shell: Shell
    environment: Mapping[str, str]
    services: Any = None  # what a stage needs from outside: `.api_key(parameter)`, `.record_client(options)`, `.model(key, guidance)`, `.deployed_environment(function)`
    llm_sources: list = field(default_factory=list)  # objects with a `.usage` list of model calls (cost accounting); a stage that calls a model adds it
    task_info: Callable[[], dict] = field(default_factory=lambda: dict)  # the Fargate task's size and start (cost accounting)
    clock: Callable[[], float] = time.monotonic
    now: Callable[[], dt.datetime] = field(default_factory=lambda: lambda: dt.datetime.now(dt.timezone.utc))

    @property
    def work(self) -> Path:
        return self.config.work_dir

    @property
    def corpus(self) -> Path:
        return self.work / "corpus"

    @property
    def run_dir(self) -> Path:
        return self.work / "runs" / self.config.week

    @property
    def config_dir(self) -> Path:
        return self.work / "config"

    @property
    def site(self) -> Path:
        return self.work / "site"

    @property
    def static_dir(self) -> Path:
        return self.site / self.config.static_subdir

    @property
    def outputs(self) -> Path:
        return self.config_dir / "amplify_outputs.json"

    def command_env(self) -> dict[str, str]:
        env = dict(self.environment)
        env.setdefault("PAPYRUS_GRAPHQL_AUTH", "iam")
        env["PAPYRUS_ALLOW_CROSS_ROOT"] = "1"
        env["PAPYRUS_PROJECTION_LEASE_PURPOSE"] = "cloud-run projection"
        if self.outputs.exists():
            from ..knowledge_snapshot.commands import endpoint_of_outputs  # noqa: PLC0415

            env["PAPYRUS_GRAPHQL_ENDPOINT"] = endpoint_of_outputs(str(self.outputs))
        return env

    def sh(self, *args: str, stdout: Path | None = None) -> None:
        self.shell(list(args), cwd=self.work, env=self.command_env(), stdout=stdout)

    def read_state(self) -> dict:
        path = self.run_dir / "state.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def write_state(self, **values: Any) -> dict:
        merged = {**self.read_state(), **values}
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "state.json").write_text(json.dumps(merged, indent=2, sort_keys=True))
        return merged

    # -- state transfer ---------------------------------------------------------------------------------------------
    def pull(self, *, corpus: bool = False, run: bool = False, site: bool = False) -> None:
        self.state.download("config/", self.config_dir)
        self.seed_config()
        if corpus:
            self.state.download("corpus/", self.corpus)
        if run:
            self.state.download(f"runs/{self.config.week}/", self.run_dir)
        if site:
            self.clone_site()

    def seed_config(self) -> None:
        """Write the default of every operator file that is missing from ``config/``, locally and into the state, never over a file that exists.

        A site that has not written a vocabulary gets the generic one (organization, product, person, topic); a site whose state has no
        ``amplify_outputs.json`` gets one holding the endpoint AppSync reports for ``appSyncApiId``. Stop words and review guidance are optional and have no default file."""
        seeds = {VOCABULARY_FILE: default_vocabulary(self.config.publication)}
        if self.config.appsync_api_id and not (self.config_dir / OUTPUTS_FILE).exists():
            # An AppSync API id is not its endpoint host, so the address is asked of AppSync (only when the file is missing).
            seeds[OUTPUTS_FILE] = default_outputs(self.services.appsync_endpoint(self.config.appsync_api_id))
        for name, text in seeds.items():
            target = self.config_dir / name
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
            self.state.write_text(f"config/{name}", text)
            print(f"config/{name} was not in the run state; seeded the default", flush=True)

    def push(self, *, corpus: bool = False, run: bool = False) -> None:
        if corpus:
            self.state.upload("corpus/", self.corpus, prune=True)
        if run:
            self.state.upload(f"runs/{self.config.week}/", self.run_dir, prune=True)

    @property
    def monitor_records(self) -> Path:
        """The monitor records ``corpus-sync`` wrote for this week (a site that sets ``monitorSources``)."""
        return self.run_dir / "monitor-records.json"

    @property
    def monitor_ledger(self) -> Path:
        """What the monitor-record import has written already (``monitor_ledger.py``); kept with the corpus, so it outlives the week's run directory."""
        return self.corpus / "monitor-import-ledger.json"

    def monitor_options(self) -> list[str]:
        """``--monitor-records FILE`` for a command that counts the records, or nothing when the site has no monitor source."""
        return ["--monitor-records", str(self.monitor_records)] if self.config.monitor_sources else []

    def import_options(self) -> list[str]:
        """The monitor options of the commands that import the records: the records, the ledger that lets a run skip what it wrote before, and
        ``--monitor-full`` (``KNOWLEDGE_MONITOR_FULL=true``) to import every record again."""
        if not self.config.monitor_sources:
            return []
        return [*self.monitor_options(), "--monitor-ledger", str(self.monitor_ledger), *(["--monitor-full"] if self.config.monitor_full else [])]

    def prepare_site(self) -> None:
        """The site checkout plus the plugin check, for every stage that writes to the site."""
        self.pull(site=True, run=bool(self.config.monitor_sources))
        self.verify_plugins()

    def nothing_to_do(self, *, needs_documents: bool = False) -> dict | None:
        """The stage's result when ``corpus-sync`` found nothing for it to work on this week, else None.

        A publication with no published items and no monitor records has nothing to model, extract, snapshot or project: every later stage
        succeeds without running a tool (its cost is still recorded). A stage that works on the items themselves (the topic model, the
        typed extraction, the AI review) also has nothing to do when only monitor records exist, which are data and never documents.
        Without ``corpus-sync``'s counts in the run state (a stage started alone) the answer is None and the stage runs as it always did."""
        self.pull(run=True)
        state = self.read_state()
        if state.get("empty") is True:
            reason = "the publication has no published items and no monitor records this week"
        elif needs_documents and state.get("documents") == 0:
            reason = "the publication has no published items this week (monitor records are data, not documents)"
        else:
            return None
        print(f"nothing to do: {reason}", flush=True)
        return {"status": "nothing to do", "reason": reason}

    def verify_plugins(self) -> None:
        """Fail before writing anything unless this stage's plugin list is the one the site's deployed Lambda uses.

        A projection without a plugin renders no pages for it, and a later cleanup would call them orphans."""
        function = (self.environment.get("KNOWLEDGE_CONTENT_ACTIONS_FUNCTION") or "").strip()
        if not function:
            raise StageFailed("KNOWLEDGE_CONTENT_ACTIONS_FUNCTION is not set; cannot check the plugin list against the deployed site.")
        ours = _plugin_set(self.environment.get("PAPYRUS_PLUGINS"))
        deployed = _plugin_set(self.services.deployed_environment(function).get("PAPYRUS_PLUGINS"))
        if ours != deployed:
            raise StageFailed(
                f"PAPYRUS_PLUGINS differs from the deployed site: this stage has {sorted(ours) or 'none'}, "
                f"the content-actions Lambda has {sorted(deployed) or 'none'}. Fix `plugins` in the knowledgeRun config."
            )

    def fallback_release(self) -> str:
        """The release to project with when the site has no requirements-publication.txt: its infra/site.json papyrusVersion, else the image's."""
        site_json = self.site / "infra" / "site.json"
        if site_json.exists():
            try:
                version = json.loads(site_json.read_text()).get("papyrusVersion")
            except (ValueError, AttributeError) as error:
                raise StageFailed(f"The site's infra/site.json is not a JSON object: {error}") from error
            if isinstance(version, str) and version.strip():
                return _pep440(version.strip())
        try:
            return importlib.metadata.version("papyrus-newsroom")
        except importlib.metadata.PackageNotFoundError as error:
            raise StageFailed("The site has no requirements-publication.txt or infra/site.json papyrusVersion, and the image has no papyrus-newsroom release to fall back on.") from error

    @property
    def pinned(self) -> Path:
        return self.work / "pinned"

    def clone_site(self) -> None:
        """Check out the site code the live site runs, never anything older, and stop if that cannot be done.

        With the Amplify app configured that is the commit of the app's latest successful deploy of the branch, so pages,
        templates and hooks equal the deployed ones even while newer commits wait. Otherwise it is the tip of the branch,
        checked against the remote (the stale-checkout guard)."""
        if self.site.exists():
            return
        repo, branch = self.config.site_repo, self.config.site_branch
        app_id = (self.environment.get("KNOWLEDGE_AMPLIFY_APP_ID") or "").strip()
        env = self.command_env()
        if app_id:
            wanted = self.services.deployed_commit(app_id, branch)
            self.shell(["git", "init", "--quiet", str(self.site)], cwd=self.work, env=env)
            self.shell(["git", "-C", str(self.site), "fetch", "--quiet", "--depth", "1", repo, wanted], cwd=self.work, env=env)
            self.shell(["git", "-C", str(self.site), "checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=self.work, env=env)
            head = _git_output(self.shell, ["git", "-C", str(self.site), "rev-parse", "HEAD"], self)
            if head != wanted:
                raise StageFailed(f"The site checkout ({head[:8]}) is not the deployed commit ({wanted[:8]}).")
            print(f"site code: {repo} at the deployed commit {wanted[:12]} of {branch}", flush=True)
            return
        self.shell(["git", "clone", "--depth", "1", "--branch", branch, repo, str(self.site)], cwd=self.work, env=env)
        head = _git_output(self.shell, ["git", "-C", str(self.site), "rev-parse", "HEAD"], self)
        tip = _git_output(self.shell, ["git", "ls-remote", repo, f"refs/heads/{branch}"], self).split()[:1]
        if not tip or tip[0] != head:
            raise StageFailed(f"The site checkout ({head[:8]}) is not the tip of {branch}; refusing to run from a stale checkout.")

    def install_pinned_papyrus(self) -> None:
        """Project with the Papyrus release the site pins, the one its Lambda runs.

        The pin is requirements-publication.txt when the site has one; otherwise `papyrus-newsroom==<papyrusVersion>` from the site's
        infra/site.json, or the image's own release when that file does not say. It is installed over the image's own copy (PYTHONPATH),
        without its dependencies, which the image provides. The pin must carry the projection lease, or the stage stops before it writes."""
        requirements = self.site / "requirements-publication.txt"
        if requirements.exists():
            pin = [line.strip() for line in requirements.read_text().splitlines() if line.strip().startswith("papyrus-newsroom")]
            if len(pin) != 1 or "==" not in pin[0]:
                raise StageFailed(f"requirements-publication.txt must pin papyrus-newsroom with ==, got {pin or 'nothing'}.")
        else:
            pin = [f"papyrus-newsroom=={self.fallback_release()}"]
            requirements = self.work / "requirements-pinned.txt"
            requirements.write_text(pin[0] + "\n")
        self.pinned.mkdir(parents=True, exist_ok=True)
        env = {**self.command_env(), "PYTHONPATH": str(self.pinned)}
        self.shell(["pip", "install", "--quiet", "--no-deps", "--target", str(self.pinned), "-r", str(requirements)], cwd=self.work, env=env)
        try:
            self.shell(["python", "-c", "import papyrus_content.projection.lease"], cwd=self.work, env=env)
        except StageFailed as error:
            raise StageFailed(f"The pinned {pin[0]} does not carry the projection lease; bump the pin to a release that does.") from error
        print(f"projecting with the site's pin: {pin[0]}", flush=True)


def _pep440(version: str) -> str:
    """The PyPI spelling of a site.json papyrusVersion: `1.0.0-next.41` is `1.0.0.dev41` (the same mapping the Amplify builds use)."""
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?:-[0-9A-Za-z-]+\.(\d+))?", version)
    if not match:
        raise StageFailed(f"The site's papyrusVersion {version!r} cannot be mapped to a PEP 440 release.")
    return match.group(1) if match.group(2) is None else f"{match.group(1)}.dev{match.group(2)}"


def _plugin_set(value: str | None) -> set[str]:
    return {name.strip() for name in (value or "").split(",") if name.strip()}


def _git_output(shell: Shell, args: list[str], run: Run) -> str:
    target = run.work / ".git-output"
    shell(args, cwd=run.work, env=run.command_env(), stdout=target)
    return target.read_text().strip()


# -- stages -----------------------------------------------------------------------------------------------------------
def knowledge_options(run: Run) -> list[str]:
    options = [
        "--auth", "iam", "--amplify-outputs", str(run.outputs),
        "--site-bucket", run.config.site_bucket,
        "--static-dir", str(run.static_dir),
        "--entity-href", ENTITY_HREF,
        "--as-of", run.config.monday.isoformat(),
        "--vocabulary", str(run.config_dir / VOCABULARY_FILE),  # only the vocabulary's kinds get wiki pages and links
    ]
    options += beats_options(run)
    if run.config.concept_kinds:
        options += ["--concept-kinds", run.config.concept_kinds]
    return options + run.monitor_options()


def backend_options(run: Run) -> list[str]:
    return ["--auth", "iam", "--amplify-outputs", str(run.outputs)]


def beats_options(run: Run) -> list[str]:
    """``--beats-config FILE`` when the site names one and its checkout has it; a site without a beats file gets a snapshot with no beats."""
    if not run.config.beats_config:
        return []
    path = run.site / run.config.beats_config
    if not path.exists():
        print(f"beats config {run.config.beats_config} is not in the site checkout; continuing without beats", flush=True)
        return []
    return ["--beats-config", str(path)]


def corpus_sync(run: Run) -> dict:
    run.pull(corpus=True, run=True, site=True)
    export = ["papyrus", "knowledge", "corpus", "export", "--out", str(run.corpus / "raw" / "papyrus"), *backend_options(run), "--static-dir", str(run.static_dir)]
    if run.config.monitor_sources:  # monitor-delivered References join the corpus as data documents, dated by their source date
        export += [
            "--monitor-sources", ",".join(run.config.monitor_sources),
            *(["--monitor-weeks", str(run.config.monitor_weeks)] if run.config.monitor_weeks is not None else []),  # optional; absent means all history
            "--corpus-key", run.config.corpus_key, "--as-of", run.config.monday.isoformat(), "--monitor-records-out", str(run.monitor_records),
        ]
    run.sh(*export)
    documents = len(list((run.corpus / "raw" / "papyrus").glob("*.md")))
    records = monitor_record_count(run)
    if documents == 0 and records == 0:  # a new site, or one whose monitors have delivered nothing: nothing for the later stages to work on
        run.write_state(empty=True, documents=0, records=0, asOf=run.config.as_of.isoformat())
        run.push(corpus=True, run=True)
        print("corpus-sync: no published items and no monitor records; the rest of the run has nothing to do", flush=True)
        return {"status": "nothing to do", "documents": 0, "records": 0}
    if not (run.corpus / "metadata").is_dir():
        run.sh("biblicus", "init", str(run.corpus))
    run.sh("biblicus", "reindex", "--corpus", str(run.corpus))
    run.sh("biblicus", "extract", "build", "--corpus", str(run.corpus), "--stage", "pass-through-text")
    latest = json.loads((run.corpus / "extracted" / "pipeline" / "latest.json").read_text())
    run.write_state(extraction=latest["snapshot_id"], asOf=run.config.as_of.isoformat(), empty=False, documents=documents, records=records)
    run.push(corpus=True, run=True)
    return {"extraction": latest["snapshot_id"]}


def monitor_record_count(run: Run) -> int:
    """How many monitor records the export wrote for this week (0 for a site without monitor sources)."""
    if not run.config.monitor_sources or not run.monitor_records.exists():
        return 0
    from ..knowledge_snapshot.monitor_records import read_records  # noqa: PLC0415

    return len(read_records(run.monitor_records))


def previous_run_id(corpus: Path) -> str | None:
    path = corpus / "knowledge-run.json"
    if not path.exists():
        return None
    return json.loads(path.read_text()).get("previousRunId") or None


def topic_model(run: Run) -> dict:
    if (idle := run.nothing_to_do(needs_documents=True)) is not None:
        return idle
    run.pull(corpus=True, run=True)
    state = run.read_state()
    extraction = state["extraction"]
    previous = previous_run_id(run.corpus)
    run_dir = run.run_dir
    stop_words = run.config_dir / "stop-words.txt"
    config_args = ["--stop-words", str(stop_words)] if stop_words.exists() else []
    run.sh("papyrus", "knowledge", "topic-config", "--out", str(run_dir / "topic-modeling.yml"), *config_args)
    run.sh(
        "biblicus", "analyze", "topics", "--corpus", str(run.corpus), "--configuration", str(run_dir / "topic-modeling.yml"),
        "--extraction-snapshot", f"pipeline:{extraction}", stdout=run_dir / "topics.json",
    )
    current = json.loads((run_dir / "topics.json").read_text())["snapshot"]["snapshot_id"]
    run.sh(
        "biblicus", "analyze", "topic-trends", "--corpus", str(run.corpus), "--topic-modeling-snapshot", current,
        "--bin", "weekly", "--weeks", TREND_WEEKS, "--as-of", run.config.as_of.isoformat(), stdout=run_dir / "trends.json",
    )
    trends = json.loads((run_dir / "trends.json").read_text())["snapshot_id"]
    identity = ["biblicus", "analyze", "topic-identity", "--corpus", str(run.corpus), "--current", current, "--trends-snapshot", trends]
    if previous and previous != current:
        identity += ["--previous", previous]
    run.sh(*identity, "--threshold", IDENTITY_THRESHOLD, stdout=run_dir / "identity.json")
    run.write_state(current=current, trends=trends, previous=previous)
    run.push(corpus=True, run=True)
    return {"current": current, "trends": trends, "previous": previous}


def typed_extraction(run: Run) -> dict:
    if (idle := run.nothing_to_do(needs_documents=True)) is not None:
        return idle
    run.pull(corpus=True, run=True)
    state = run.read_state()
    run_dir = run.run_dir
    publish = ["papyrus", "knowledge", "publish-run", *backend_options(run), "--corpus-key", run.config.corpus_key, "--actor-name", run.config.actor_name, *run.import_options()]
    run.sh(*publish)  # the dry run: its plan is in the task log
    run.sh(*publish, "--apply")  # front-matter entities first, so the extractor resolves to accepted entities
    run.sh(
        "papyrus", "knowledge", "entities", "registry", *backend_options(run),
        "--out", str(run_dir / "registry.json"), "--vocabulary", str(run.config_dir / "vocabulary.yml"),
    )
    run.sh(
        "biblicus", "extract", "typed-entities", "--corpus", str(run.corpus), "--vocabulary", str(run.config_dir / "vocabulary.yml"),
        "--registry", str(run_dir / "registry.json"), "--extraction-snapshot", f"pipeline:{state['extraction']}",
        "--out", str(run_dir / "typed"), stdout=run_dir / "typed-stdout.json",
    )
    run.push(corpus=True, run=True)
    return {"typed": str(run_dir / "typed" / "output.json")}


def import_arguments(run: Run) -> list[str]:
    state = run.read_state()
    if state.get("documents") == 0:  # only monitor records this week: no clusters, no extracted entities, just the records
        return ["papyrus", "knowledge", "publish-run", *backend_options(run), "--corpus-key", run.config.corpus_key, "--actor-name", run.config.actor_name, *run.import_options()]
    return [
        "papyrus", "knowledge", "publish-run", *backend_options(run),
        "--corpus-key", run.config.corpus_key, "--actor-name", run.config.actor_name, *run.import_options(),
        "--identity", str(run.corpus / "analysis" / "topic-identity" / state["current"] / "output.json"),
        "--trends", str(run.corpus / "analysis" / "topic-governance" / state["trends"] / "output.json"),
        "--entities", str(run.run_dir / "typed" / "output.json"),
    ]


def publish_run(run: Run) -> dict:
    if (idle := run.nothing_to_do()) is not None:
        return idle
    run.pull(corpus=True, run=True)
    state = run.read_state()
    arguments = import_arguments(run)
    run.sh(*arguments)
    run.sh(*arguments, "--apply")
    if state.get("documents") == 0:  # no topic run this week: next week still compares with the last one that was imported
        return {"status": "records only"}
    record = {"previousRunId": state["current"], "runOn": run.config.as_of.isoformat(), "trendsSnapshotId": state["trends"]}
    (run.corpus / "knowledge-run.json").write_text(json.dumps(record) + "\n")
    run.push(corpus=True)
    return record


def publish_relations(run: Run) -> dict:
    """Import again after the review: relations between entities that are now accepted."""
    if (idle := run.nothing_to_do()) is not None:
        return idle
    run.pull(corpus=True, run=True)
    run.sh(*import_arguments(run), "--apply")
    return {}


def ai_review(run: Run) -> dict:
    """AI review (GPT-6 Luna) of the entities, clusters and relations the import left unreviewed; evidence or no change."""
    from ..knowledge_snapshot import commands as c  # noqa: PLC0415
    from ..knowledge_snapshot.actors import make_actor  # noqa: PLC0415
    from ..knowledge_snapshot.monitor_records import read_records  # noqa: PLC0415
    from ..records import apply_record_changes  # noqa: PLC0415
    from . import ai_review as review  # noqa: PLC0415

    if (idle := run.nothing_to_do(needs_documents=True)) is not None:
        return idle
    run.pull(corpus=True, run=True)
    state = run.read_state()
    guidance_file = run.config_dir / "review-guidance.md"
    guidance = guidance_file.read_text() if guidance_file.exists() else ""
    model = run.services.model(run.services.api_key(run.config.openai_parameter), guidance)
    run.llm_sources.append(model)  # its `usage` is read for the stage's cost even if the review fails half way
    client = run.services.record_client({"auth": "iam", "amplify-outputs": str(run.outputs)})
    actor = make_actor("ai", None, c.today())
    now = c.utc_now()
    typed_path = run.run_dir / "typed" / "output.json"
    texts_dir = run.corpus / "extracted" / "pipeline" / state["extraction"] / "text"
    texts = {path.stem: path.read_text() for path in texts_dir.glob("*.txt")}
    typed = review.TypedRun(json.loads(typed_path.read_text()), texts)
    labels = review.vocabulary_labels((run.config_dir / "vocabulary.yml").read_text())

    def mentions_of(node: dict) -> list[dict]:
        return [row for row in c.relations_of_nodes(client, [node]) if c.is_item_mention(row)]

    patches: list[dict] = []
    decisions: list[review.Decision] = []

    nodes = c.current_nodes(client.list_records("SemanticNode"))
    generated = [node for node in nodes if node.get("status") == "generated"]
    found, made = review.review_entities(generated, typed, mentions_of, model, actor, now=now, vocabulary=labels)
    patches += found
    decisions += made

    titles = {}
    for item in c.published_items(client.list_published_item_summaries(), c._no_url):
        titles[item.key] = titles[item.item_id] = item.title or ""
    if run.config.monitor_sources:  # a cluster of Hub models can be named from their ids
        for record in read_records(run.monitor_records):
            titles[record.lineage_id] = titles[record.reference_id] = record.title
    found, made = review.review_clusters(
        client.list_records("SteeringProposal"), lambda ids: [titles[i] for i in ids if titles.get(i)], model, actor, now=now
    )
    patches += found
    decisions += made

    # Entities accepted just now count as accepted for the relation review below.
    accepted_now = {patch["expected"]["id"] for patch in patches if patch["modelName"] == "SemanticNode" and patch["expected"].get("status") == "accepted"}
    if patches:
        apply_record_changes(client, review.record_changes(patches))
        patches = []
        nodes = c.current_nodes(client.list_records("SemanticNode"))
    accepted = [node for node in nodes if node.get("status") == "accepted"]
    by_lineage = {str(node.get("lineageId") or node["id"]): node for node in accepted}
    relations = c.relations_of_nodes(client, accepted, workers=c.DEFAULT_WORKERS, client_factory=getattr(run.services, "worker_client", None))
    found, made = review.review_relations(relations, by_lineage, typed, model, actor, now=now)
    patches += found
    decisions += made
    if patches:
        apply_record_changes(client, review.record_changes(patches))

    log = {"week": run.config.week, "model": model.model, "calls": model.calls, "summary": review.summary_of(decisions), "decisions": [d.to_dict() for d in decisions], "acceptedNow": len(accepted_now)}
    if run.config.monitor_sources and run.config.monitor_suggestions:
        log["monitorSuggestions"] = suggest_promotions(run, client)
    run.run_dir.mkdir(parents=True, exist_ok=True)
    (run.run_dir / "ai-review.json").write_text(json.dumps(log, indent=2, sort_keys=True))
    run.push(run=True)
    return {"calls": model.calls, "summary": log["summary"]}


def suggest_promotions(run: Run, client: Any) -> dict:
    """The week's monitor records most worth a look, as ONE soft review request (idempotent per week). Never fails the run.

    The first pass is the Hub's own interest (likes, then downloads) among the records of the last four weeks that no item carries
    yet; nobody is asked to publish anything, only to promote the ones worth a story (``papyrus references promote``)."""
    from .. import review_requests  # noqa: PLC0415
    from ..knowledge_snapshot.monitor_records import read_records  # noqa: PLC0415
    from ..monitor_promotion import promoted_reference_ids, suggest  # noqa: PLC0415

    try:
        records = read_records(run.monitor_records)
        picks = suggest(records, limit=run.config.monitor_suggestions, as_of=run.config.monday, promoted=promoted_reference_ids(client, records))
        if not picks:
            return {"status": "none", "records": len(records), "suggested": []}
        suggested = [{"referenceId": record.reference_id, "model": record.model_id, "url": record.url, "likes": record.details.get("likes"), "downloads": record.details.get("downloads")} for record in picks]
        request = review_requests.raise_review(
            client,
            subject={"type": "batch", "id": f"monitor-records-{run.config.publication}-{run.config.week}"},
            mode="soft_review",
            raised_by="knowledge-run",
            reason=f"{len(picks)} monitor record{'s' if len(picks) != 1 else ''} worth a look this week",
            ask="Promote the ones worth a story with `papyrus references promote <reference id> --section <section>` (it saves a draft; nothing is published). Approve when you have looked, or steer with a note.",
            links=[{"label": f"{record.model_id} ({record.reference_id})", "url": record.url} for record in picks],
            request_id=f"rr-monitor-records-{run.config.publication}-{run.config.week}".lower(),
        )
        return {"status": "requested", "requestId": request["id"], "records": len(records), "suggested": suggested}
    except Exception as error:  # noqa: BLE001 - a site without review requests, or a missing file, must not fail the run
        return {"status": "not_raised", "error": f"{type(error).__name__}: {error}"[:300]}


def snapshot(run: Run) -> dict:
    if (idle := run.nothing_to_do()) is not None:
        return idle
    run.prepare_site()
    run.sh("papyrus", "knowledge", "snapshot", *knowledge_options(run))
    return {"asOf": run.config.monday.isoformat()}


def archive(run: Run) -> dict:
    if (idle := run.nothing_to_do()) is not None:
        return idle
    run.prepare_site()
    entry = f"{ARCHIVE_DIRECTORY}/{run.config.monday.isoformat()}.json"
    stored = run.services.read_object(run.config.site_bucket, entry)
    if stored is not None:
        # An entry is immutable and the pipeline never replaces one: a second run in the week keeps the week's first.
        try:
            kept = json.loads(stored)
            run_id, as_of = kept["runId"], kept["asOf"]
        except (ValueError, KeyError, TypeError) as error:
            raise StageFailed(f"The archive entry {entry} exists but is unreadable ({type(error).__name__}); not replacing it and not skipping it.") from error
        if as_of != run.config.monday.isoformat():
            raise StageFailed(f"The archive entry {entry} says it is for {as_of}, not {run.config.monday}; not skipping it.")
        print(f"archive: kept-existing (run {run_id}): week {as_of} is already archived in {entry}", flush=True)
        return {"asOf": as_of, "archive": f"kept-existing (run {run_id})"}
    run.sh("papyrus", "knowledge", "archive", *knowledge_options(run))  # never --replace: a week's entry is immutable
    return {"asOf": run.config.monday.isoformat()}


def wiki_sync(run: Run) -> dict:
    if (idle := run.nothing_to_do()) is not None:
        return idle
    run.pull(site=True, run=bool(run.config.monitor_sources))
    sync = ["papyrus", "knowledge", "wiki", "sync", *backend_options(run), *run.monitor_options()]
    sync += beats_options(run)
    sync += ["--vocabulary", str(run.config_dir / VOCABULARY_FILE), "--retire"]  # pages of kinds the vocabulary does not declare come down
    run.sh(*sync)  # the dry run: its plan, with every page it would retire, is in the task log
    run.run_dir.mkdir(parents=True, exist_ok=True)
    run.sh(*sync, "--apply", "--retired-out", str(run.run_dir / RETIRED_FILE))  # drafts only
    # --no-trigger: publishing must not project; the projection stage does that once, under the lease, last.
    run.sh("papyrus", "knowledge", "wiki", "publish", *backend_options(run), "--all-drafts", "--actor", "ai", "--apply", "--no-trigger")
    run.push(run=True)  # the retired pages, for the projection stage
    return {"retired": len(retired_items(run))}


def retired_items(run: Run) -> list[str]:
    """The source item ids of the wiki pages this run took down: the projection removes their pages."""
    path = run.run_dir / RETIRED_FILE
    return json.loads(path.read_text()) if path.exists() else []


def projection(run: Run) -> dict:
    if (idle := run.nothing_to_do()) is not None:
        return idle
    run.prepare_site()
    arguments = ["papyrus", "ops", "content", "project", "--all", "--static-dir", str(run.static_dir), "--bucket", run.config.site_bucket, "--json"]
    assert not set(FORBIDDEN_FLAGS) & set(arguments)  # the #565 guard stays on; a bad run must never delete pages
    run.install_pinned_papyrus()
    environment = {**run.command_env(), "PYTHONPATH": str(run.pinned)}
    taken_down = retired_items(run)
    if taken_down:
        # A bulk projection never deletes the pages of an unpublished item, so the retired pages go first, in one pass. The pinned
        # release may predate `--unpublished-items`; the image's own papyrus does it (the bulk projection after it re-renders with the pin).
        listed = run.work / RETIRED_FILE
        listed.write_text(json.dumps(taken_down))
        run.shell(
            ["papyrus", "ops", "content", "project", "--unpublished-items", str(listed), "--static-dir", str(run.static_dir), "--bucket", run.config.site_bucket, "--json"],
            cwd=run.work, env=run.command_env(), stdout=run.work / "retired-projection.json",
        )
        print(f"retired wiki pages projected away ({len(taken_down)}): {(run.work / 'retired-projection.json').read_text().strip()[:2000]}", flush=True)
    run.shell(arguments, cwd=run.work, env=environment, stdout=run.work / "projection.json")
    raw = (run.work / "projection.json").read_text()
    print(f"projection report: {raw.strip()}", flush=True)  # the report is the evidence of what a run wrote and deleted
    return first_json_object(raw)


def first_json_object(text: str) -> dict:
    """The projection report in a command's output: the first JSON object with a `written` count. The output also carries
    other lines, among them CloudWatch metric lines that are JSON too."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, end = decoder.raw_decode(text[start:])
        except ValueError:
            start = text.find("{", start + 1)
            continue
        if isinstance(value, dict) and "written" in value:
            return value
        start = text.find("{", start + end)
    raise StageFailed("The projection printed no report (a JSON object with a `written` count).")


STAGE_FUNCTIONS: dict[str, Callable[[Run], dict]] = {
    "corpus-sync": corpus_sync,
    "topic-model": topic_model,
    "typed-extraction": typed_extraction,
    "publish-run": publish_run,
    "ai-review": ai_review,
    "publish-relations": publish_relations,
    "snapshot": snapshot,
    "archive": archive,
    "wiki-sync": wiki_sync,
    "projection": projection,
}


def run_stage(stage: str, run: Run, functions: Mapping[str, Callable[[Run], dict]] | None = None) -> int:
    """Run one stage; returns the process exit code (0 done or already done, 1 failed)."""
    table = functions or STAGE_FUNCTIONS
    if stage not in STAGES or stage not in table:
        print(f"unknown stage {stage!r}", file=sys.stderr)
        return 2
    if run.ledger.status(stage) == SUCCEEDED:
        print(f"stage {stage} already succeeded in execution {run.config.execution_name}; nothing to do")
        return 0
    earlier = _safely(lambda: run.ledger.cost(stage))  # what failed attempts of this stage in this execution already cost
    attempt = run.ledger.begin(stage)
    began = run.clock()
    print(f"stage {stage} of {run.config.publication} {run.config.week}, execution {run.config.execution_name}, attempt {attempt}", flush=True)
    try:
        if run.config.failure_injection_allowed and run.config.fail_stage == stage:
            raise StageFailed(f"injected failure at {stage} (test execution {run.config.execution_name})")
        details = table[stage](run)
    except Exception as error:  # noqa: BLE001 - the ledger records it and the task fails so Step Functions retries or stops
        cost = _stage_cost(run, began, earlier)
        run.ledger.fail(stage, f"{type(error).__name__}: {error}", cost)
        print(f"stage {stage} failed: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1
    details = _plain(details)
    cost = _stage_cost(run, began, earlier)
    if cost is not None:
        details["cost"] = cost
    run.ledger.finish(stage, details)
    print(f"stage {stage} succeeded" + (f" (cost ${cost['totalUsd']:.4f})" if cost else ""), flush=True)
    if stage == PROJECTION_STAGE:
        _record_run_total(run)
    return 0


def _safely(action: Callable[[], Any]) -> Any:
    """Cost accounting must never fail a stage: an error is logged and the figure is left out."""
    try:
        return action()
    except Exception as error:  # noqa: BLE001
        print(f"cost accounting skipped: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return None


def _stage_cost(run: Run, began: float, earlier: dict | None) -> dict | None:
    def build() -> dict:
        calls = [call for source in run.llm_sources for call in getattr(source, "usage", [])]
        latest = costs.stage_cost(elapsed_seconds=run.clock() - began, task=run.task_info(), now=run.now(), calls=calls)
        return costs.add_attempt(earlier, latest)

    return _safely(build)


def _record_run_total(run: Run) -> None:
    """After the last stage: sum the execution's stages into the ledger's run row and `runs/<week>/cost-<execution>.json`, and log it."""

    def record() -> None:
        total = costs.run_total(run.ledger.rows(), STAGES)
        run.ledger.write_run_total(total)
        report = {"publication": run.config.publication, "week": run.config.week, "execution": run.config.execution_name, "cost": total}
        run.state.write_text(f"runs/{run.config.week}/cost-{run.config.execution_name}.json", json.dumps(report, indent=2, sort_keys=True))
        print(f"run cost: ${total['totalUsd']:.4f} (compute ${total['computeUsd']:.4f}, model ${total['llm']['usd']:.4f}) in {total['durationSeconds']}s" + (" [partial]" if total.get("partial") else ""), flush=True)

    _safely(record)


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))
