from __future__ import annotations

from behave import given, then

# These steps extend the agent-readable site of agent_readable_pages_steps.py (same context.agent_* state).

ACTIONS_MAIN_HOOK = (
    "def main(page):\n"
    "    if page.kind != 'item':\n"
    "        return None\n"
    "    return '<article id=\"own\">' + page.article_actions() + page.fragment + '</article>'\n"
)


def listed(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


@given('the page actions use the icon display with "{actions}"')
def agent_icon_actions(context, actions: str) -> None:
    context.agent_settings["pageActions"] = {
        **context.agent_settings["pageActions"],
        "display": "icons",
        "actions": ["view", "copy", *listed(actions)],
    }


@given("the site has its own article template that places the page actions with article_actions")
def agent_own_template(context) -> None:
    context.agent_settings["hooks"] = "hooks.py"
    context.agent_files["hooks.py"] = ACTIONS_MAIN_HOOK


@given("the site does not link the component stylesheet")
def agent_no_component_stylesheet(context) -> None:
    context.agent_settings["site"] = {**context.agent_settings["site"], "componentsCss": False}


@then('the agent site has these pages: "{keys}"')
def agent_has(context, keys: str) -> None:
    missing = [key for key in listed(keys) if key not in context.site.tree]
    assert not missing, missing
