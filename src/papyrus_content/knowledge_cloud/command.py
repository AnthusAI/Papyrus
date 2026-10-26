"""``papyrus knowledge cloud-run --stage NAME``: one stage of the scheduled knowledge run (the container's command)."""

from __future__ import annotations

import os
import sys

from ..options import normalize_string, parse_options
from .config import STAGES, CloudRunConfig, ConfigError
from .ledger import RunLedger
from .stages import Run, run_shell, run_stage
from .state import StateStore


def latest_successful_commit(jobs: list[dict], app_id: str, branch: str) -> str:
    """The commit of the successful job that ended last: what the live site was built from, whatever order the jobs are listed in."""
    done = [job for job in jobs if job.get("status") == "SUCCEED" and job.get("commitId") and job.get("endTime")]
    if not done:
        raise ValueError(f"No successful Amplify deploy of {branch} found for app {app_id}.")
    return max(done, key=lambda job: job["endTime"])["commitId"]


class AwsServices:
    """What the AI review reaches outside the container for: the OpenAI key (SSM SecureString) and the backend client."""

    def __init__(self, region: str, max_calls: int) -> None:
        import boto3

        self._ssm = boto3.client("ssm", region_name=region)
        self._lambda = boto3.client("lambda", region_name=region)
        self._amplify = boto3.client("amplify", region_name=region)
        self._s3 = boto3.client("s3", region_name=region)
        self._max_calls = max_calls

    def api_key(self, parameter: str) -> str:
        return self._ssm.get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"]

    def deployed_environment(self, function: str) -> dict[str, str]:
        configuration = self._lambda.get_function_configuration(FunctionName=function)
        return dict((configuration.get("Environment") or {}).get("Variables") or {})

    def read_object(self, bucket: str, key: str) -> bytes | None:
        from botocore.exceptions import ClientError

        try:
            return self._s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        except ClientError as error:
            if error.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def deployed_commit(self, app_id: str, branch: str) -> str:
        """The commit of the app's most recent successful deploy of the branch."""
        jobs: list[dict] = []
        token = None
        while True:
            page = self._amplify.list_jobs(appId=app_id, branchName=branch, maxResults=50, **({"nextToken": token} if token else {}))
            jobs += page["jobSummaries"]
            token = page.get("nextToken")
            if not token or len(jobs) >= 200:
                break
        return latest_successful_commit(jobs, app_id, branch)

    def record_client(self, options: dict):
        from ..knowledge_snapshot.commands import authoring_client

        return authoring_client(options)

    def worker_client(self):
        """A client of its own for a worker thread (no announcement line)."""
        from ..knowledge_snapshot.commands import new_client

        return new_client()

    def model(self, api_key: str, guidance: str):
        from .ai_review import LunaReviewer

        return LunaReviewer(api_key, guidance=guidance, max_calls=self._max_calls)


def knowledge_cloud_run(flags: list[str]) -> None:
    options = parse_options(flags)
    stage = normalize_string(options.get("stage"))
    if stage not in STAGES:
        raise ValueError(f"--stage must be one of: {', '.join(STAGES)}.")
    import boto3

    try:
        config = CloudRunConfig.from_environment(os.environ)
    except ConfigError as error:
        raise ValueError(str(error)) from error
    table = boto3.resource("dynamodb", region_name=config.region).Table(config.ledger_table)
    ledger = RunLedger(table, config.publication, config.week, config.execution_name)
    state = StateStore(boto3.client("s3", region_name=config.region), config.state_bucket, config.state_prefix)
    max_calls = int(os.environ.get("KNOWLEDGE_REVIEW_MAX_CALLS") or 150)
    run = Run(config=config, state=state, ledger=ledger, shell=run_shell, environment=dict(os.environ), services=AwsServices(config.region, max_calls))
    config.work_dir.mkdir(parents=True, exist_ok=True)
    code = run_stage(stage, run)
    if code != 0:
        sys.exit(code)
