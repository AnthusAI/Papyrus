"""The stages of the cloud knowledge run: the workstation runbook (docs/knowledge-workstation-run.md) as container tasks.

Each stage downloads the state it needs from S3, runs the same commands an operator would, uploads what changed and
records itself in the run ledger. Stages are idempotent. The stage list ends with ``projection``; the state machine
never reaches it after a failure, and ``projection`` never passes ``--allow-deletions``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import STAGES, CloudRunConfig
from .ledger import SUCCEEDED, RunLedger
from .state import StateStore

IDENTITY_THRESHOLD = "0.5"
TREND_WEEKS = "26"
ENTITY_HREF = "/wiki/{slug}/"
DELETION_FLAG = "--allow-deletions"
ARCHIVE_DIRECTORY = "_data/knowledge/history"
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
        raise StageFailed(f"`{args[0]} {args[1] if len(args) > 1 else ''}` exited with {result.returncode}")


@dataclass
class Run:
    config: CloudRunConfig
    state: StateStore
    ledger: RunLedger
    shell: Shell
    environment: Mapping[str, str]
    services: Any = None  # what a stage needs from outside: `.api_key(parameter)`, `.record_client(options)`, `.model(key, guidance)`, `.deployed_environment(function)`

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
        if corpus:
            self.state.download("corpus/", self.corpus)
        if run:
            self.state.download(f"runs/{self.config.week}/", self.run_dir)
        if site:
            self.clone_site()

    def push(self, *, corpus: bool = False, run: bool = False) -> None:
        if corpus:
            self.state.upload("corpus/", self.corpus, prune=True)
        if run:
            self.state.upload(f"runs/{self.config.week}/", self.run_dir, prune=True)

    @property
    def monitor_records(self) -> Path:
        """The monitor records ``corpus-sync`` wrote for this week (a site that sets ``monitorSources``)."""
        return self.run_dir / "monitor-records.json"

    def monitor_options(self) -> list[str]:
        """``--monitor-records FILE`` for a command that counts the records, or nothing when the site has no monitor source."""
        return ["--monitor-records", str(self.monitor_records)] if self.config.monitor_sources else []

    def prepare_site(self) -> None:
        """The site checkout plus the plugin check, for every stage that writes to the site."""
        self.pull(site=True, run=bool(self.config.monitor_sources))
        self.verify_plugins()

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
        """Project with the Papyrus release the site pins (requirements-publication.txt), the one its Lambda runs.

        It is installed over the image's own copy (PYTHONPATH), without its dependencies, which the image provides. The pin
        must carry the projection lease, or the stage stops before it writes."""
        requirements = self.site / "requirements-publication.txt"
        if not requirements.exists():
            raise StageFailed("The site has no requirements-publication.txt, so its Papyrus pin is unknown.")
        pin = [line.strip() for line in requirements.read_text().splitlines() if line.strip().startswith("papyrus-newsroom")]
        if len(pin) != 1 or "==" not in pin[0]:
            raise StageFailed(f"requirements-publication.txt must pin papyrus-newsroom with ==, got {pin or 'nothing'}.")
        self.pinned.mkdir(parents=True, exist_ok=True)
        env = {**self.command_env(), "PYTHONPATH": str(self.pinned)}
        self.shell(["pip", "install", "--quiet", "--no-deps", "--target", str(self.pinned), "-r", str(requirements)], cwd=self.work, env=env)
        try:
            self.shell(["python", "-c", "import papyrus_content.projection.lease"], cwd=self.work, env=env)
        except StageFailed as error:
            raise StageFailed(f"The pinned {pin[0]} does not carry the projection lease; bump the pin to a release that does.") from error
        print(f"projecting with the site's pin: {pin[0]}", flush=True)


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
    ]
    if run.config.beats_config:
        options += ["--beats-config", str(run.site / run.config.beats_config)]
    if run.config.concept_kinds:
        options += ["--concept-kinds", run.config.concept_kinds]
    return options + run.monitor_options()


def backend_options(run: Run) -> list[str]:
    return ["--auth", "iam", "--amplify-outputs", str(run.outputs)]


def corpus_sync(run: Run) -> dict:
    run.pull(corpus=True, run=True, site=True)
    export = ["papyrus", "knowledge", "corpus", "export", "--out", str(run.corpus / "raw" / "papyrus"), *backend_options(run), "--static-dir", str(run.static_dir)]
    if run.config.monitor_sources:  # monitor-delivered References join the corpus as data documents, dated by their source date
        export += [
            "--monitor-sources", ",".join(run.config.monitor_sources), "--monitor-weeks", str(run.config.monitor_weeks),
            "--corpus-key", run.config.publication, "--as-of", run.config.monday.isoformat(), "--monitor-records-out", str(run.monitor_records),
        ]
    run.sh(*export)
    if not (run.corpus / "metadata").is_dir():
        run.sh("biblicus", "init", str(run.corpus))
    run.sh("biblicus", "reindex", "--corpus", str(run.corpus))
    run.sh("biblicus", "extract", "build", "--corpus", str(run.corpus), "--stage", "pass-through-text")
    latest = json.loads((run.corpus / "extracted" / "pipeline" / "latest.json").read_text())
    run.write_state(extraction=latest["snapshot_id"], asOf=run.config.as_of.isoformat())
    run.push(corpus=True, run=True)
    return {"extraction": latest["snapshot_id"]}


def previous_run_id(corpus: Path) -> str | None:
    path = corpus / "knowledge-run.json"
    if not path.exists():
        return None
    return json.loads(path.read_text()).get("previousRunId") or None


def topic_model(run: Run) -> dict:
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
    run.pull(corpus=True, run=True)
    state = run.read_state()
    run_dir = run.run_dir
    publish = ["papyrus", "knowledge", "publish-run", *backend_options(run), "--corpus-key", run.config.publication, "--actor-name", run.config.actor_name, *run.monitor_options()]
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
    return [
        "papyrus", "knowledge", "publish-run", *backend_options(run),
        "--corpus-key", run.config.publication, "--actor-name", run.config.actor_name, *run.monitor_options(),
        "--identity", str(run.corpus / "analysis" / "topic-identity" / state["current"] / "output.json"),
        "--trends", str(run.corpus / "analysis" / "topic-governance" / state["trends"] / "output.json"),
        "--entities", str(run.run_dir / "typed" / "output.json"),
    ]


def publish_run(run: Run) -> dict:
    run.pull(corpus=True, run=True)
    state = run.read_state()
    arguments = import_arguments(run)
    run.sh(*arguments)
    run.sh(*arguments, "--apply")
    record = {"previousRunId": state["current"], "runOn": run.config.as_of.isoformat(), "trendsSnapshotId": state["trends"]}
    (run.corpus / "knowledge-run.json").write_text(json.dumps(record) + "\n")
    run.push(corpus=True)
    return record


def publish_relations(run: Run) -> dict:
    """Import again after the review: relations between entities that are now accepted."""
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

    run.pull(corpus=True, run=True)
    state = run.read_state()
    guidance_file = run.config_dir / "review-guidance.md"
    guidance = guidance_file.read_text() if guidance_file.exists() else ""
    model = run.services.model(run.services.api_key(run.config.openai_parameter), guidance)
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
    relations = [row for row in c.relations_of_nodes(client, accepted)]
    found, made = review.review_relations(relations, by_lineage, typed, model, actor, now=now)
    patches += found
    decisions += made
    if patches:
        apply_record_changes(client, review.record_changes(patches))

    log = {"week": run.config.week, "model": model.model, "calls": model.calls, "summary": review.summary_of(decisions), "decisions": [d.to_dict() for d in decisions], "acceptedNow": len(accepted_now)}
    run.run_dir.mkdir(parents=True, exist_ok=True)
    (run.run_dir / "ai-review.json").write_text(json.dumps(log, indent=2, sort_keys=True))
    run.push(run=True)
    return {"calls": model.calls, "summary": log["summary"]}


def snapshot(run: Run) -> dict:
    run.prepare_site()
    run.sh("papyrus", "knowledge", "snapshot", *knowledge_options(run))
    return {"asOf": run.config.monday.isoformat()}


def archive(run: Run) -> dict:
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
    run.pull(site=True, run=bool(run.config.monitor_sources))
    sync = ["papyrus", "knowledge", "wiki", "sync", *backend_options(run), *run.monitor_options()]
    if run.config.beats_config:
        sync += ["--beats-config", str(run.site / run.config.beats_config)]
    run.sh(*sync)
    run.sh(*sync, "--apply")  # drafts only
    # --no-trigger: publishing must not project; the projection stage does that once, under the lease, last.
    run.sh("papyrus", "knowledge", "wiki", "publish", *backend_options(run), "--all-drafts", "--actor", "ai", "--apply", "--no-trigger")
    return {}


def projection(run: Run) -> dict:
    run.prepare_site()
    arguments = ["papyrus", "ops", "content", "project", "--all", "--static-dir", str(run.static_dir), "--bucket", run.config.site_bucket, "--json"]
    assert not set(FORBIDDEN_FLAGS) & set(arguments)  # the #565 guard stays on; a bad run must never delete pages
    run.install_pinned_papyrus()
    run.shell(arguments, cwd=run.work, env={**run.command_env(), "PYTHONPATH": str(run.pinned)}, stdout=run.work / "projection.json")
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
    attempt = run.ledger.begin(stage)
    print(f"stage {stage} of {run.config.publication} {run.config.week}, execution {run.config.execution_name}, attempt {attempt}", flush=True)
    try:
        if run.config.failure_injection_allowed and run.config.fail_stage == stage:
            raise StageFailed(f"injected failure at {stage} (test execution {run.config.execution_name})")
        details = table[stage](run)
    except Exception as error:  # noqa: BLE001 - the ledger records it and the task fails so Step Functions retries or stops
        run.ledger.fail(stage, f"{type(error).__name__}: {error}")
        print(f"stage {stage} failed: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1
    run.ledger.finish(stage, _plain(details))
    print(f"stage {stage} succeeded", flush=True)
    return 0


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))
