import json
import subprocess
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]


@given("a site with {nodes:d} concepts")
def step_site(context, nodes):
    context.resolver = {"nodes": nodes}


@when("the labels of {links:d} concept links and {references:d} related References are resolved")
def step_resolve(context, links, references):
    payload = json.dumps({**context.resolver, "links": links, "references": references})
    done = subprocess.run(["npx", "tsx", str(REPO_ROOT / "scripts" / "link-resolver-probe.ts"), payload], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    context.resolver["result"] = json.loads(done.stdout.strip().splitlines()[-1])


@then("{concepts:d} concepts and {references:d} References were each read once by id")
def step_counts(context, concepts, references):
    result = context.resolver["result"]
    assert (result["concepts"], result["references"]) == (concepts, references), result
    assert result["labelled"] == "concept-0", result


@then("no request listed all the concepts or all the References")
def step_no_scan(context):
    assert context.resolver["result"]["all"] == 0, context.resolver["result"]
