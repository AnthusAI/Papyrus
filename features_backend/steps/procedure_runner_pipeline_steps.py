from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_procedure_runner_pipeline as t  # noqa: E402


@given("the files the runner image is built from")
def step_files(context):
    import tempfile

    context.dir = Path(tempfile.mkdtemp())
    (context.dir / "src").mkdir()
    (context.dir / "src" / "a.py").write_text("one")
    t.build_image.ROOT = context.dir
    context.tag = t.build_image.image_tag(["src/a.py"])


@when("one of them changes")
def step_change(context):
    (context.dir / "src" / "a.py").write_text("two")


@then("the image tag changes")
def step_tag_changes(context):
    context.changed = t.build_image.image_tag(["src/a.py"])
    assert context.changed != context.tag


@then("an unchanged tree has the same tag")
def step_same(context):
    assert t.build_image.image_tag(["src/a.py"]) == context.changed


@given("the release configuration")
def step_config(context):
    context.stacks = t.stacks()


@then("the runner stack builds its image with the image build script and receives it as ImageUri")
def step_builds(context):
    assert context.stacks["papyrus-procedure-runner"]["builds"] == [{"parameter": "ImageUri", "script": "infra/procedures/build_image.py", "kind": "image", "args": []}]


@then("the runner stack comes after the monitoring stack it reads its API ids from")
def step_order(context):
    names = list(context.stacks)
    assert names.index("papyrus-monitoring") < names.index("papyrus-procedure-runner")


@then("the repository stack imports the existing repository and retains it")
def step_repo(context):
    repository = context.stacks["papyrus-procedure-runner-repository"]
    assert repository["import"]["lookup"]["kind"] == "ecrRepositoryByName"
    assert "DeletionPolicy: Retain" in (t.ROOT / repository["template"]).read_text()


@then("the hand build script no longer exists")
def step_no_script(context):
    assert not (t.ROOT / "infra" / "procedures" / "build_image.sh").exists()


@given("the runner stack template")
def step_template(context):
    context.template_text = t.template_text()


@then("its role may call every site's API")
def step_apis(context):
    for site in t.SITES:
        assert f"${{{site}ApiId}}/types/Query/fields/*" in context.template_text and f"${{{site}ApiId}}/types/Mutation/fields/*" in context.template_text


@then("the template names no API id")
def step_no_ids(context):
    import re
    assert not re.search(r"[a-z0-9]{26}", context.template_text)


@then("a change to the runner template or to the code in the image plans the runner stack")
def step_plans(context):
    t.test_a_pull_request_that_touches_the_runner_plans_the_runner_stack_and_a_code_change_rebuilds_it()


@then("a removal or replacement in the runner stack that is not on the allowed list is a violation")
def step_violation(context):
    t.test_a_remove_or_replace_in_the_runner_stack_that_is_not_on_the_allowed_list_stops_the_run()
