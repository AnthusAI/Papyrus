Feature: A reconcile never deletes the pages a plugin projects
  A plugin such as the newsletter writes real pages into the site store, for
  example newsletter/confirm/index.html. The projector plans those pages only
  when it is told the plugin is enabled. The deployed backend tells it through
  PAPYRUS_PLUGINS, and a run of papyrus ops content project from a workstation
  reads the same list from custom.papyrusPlugins in amplify_outputs.json, with
  an explicit PAPYRUS_PLUGINS environment variable taking precedence. A run
  that was not told about the plugin would see its pages as pages that nothing
  expects, and a reconcile would delete them. So a reconcile that is not a dry
  run refuses to start when the plugin list it would use is unknown or differs
  from the deployed one, and whatever list it uses it never deletes a page
  under a known plugin's page prefix unless the plugin is known to be disabled
  for the site. The --only option limits the orphans a reconcile considers to
  those under a site-relative prefix, below the site's base path if it has one.

  Background:
    Given a projected site with the newsletter plugin enabled

  Scenario: A reconcile that does not know the plugin refuses and deletes nothing
    When the site is reconciled with no plugins
    Then the reconcile is refused
    And the refusal names the six newsletter pages
    And the stored pages are exactly as they were

  Scenario: A dry run that does not know the plugin does not call its pages orphans
    When the site is reconciled as a dry run with no plugins
    Then no orphan pages are listed
    And the six newsletter pages are reported as kept plugin pages
    And no drift is reported

  Scenario: A reconcile with the deployed plugin list keeps the pages
    When the site is reconciled with the plugin "newsletter"
    Then the reconcile is not refused
    And the six newsletter pages still exist

  Scenario: A plugin that is known to be disabled has its pages cleaned up
    When the site is reconciled with no plugins and the newsletter plugin known to be disabled
    Then the reconcile is not refused
    And the six newsletter pages no longer exist

  Scenario: --only limits the orphans to a path prefix
    Given the store holds the stray pages "wiki/page/a/index.html", "wiki/page/b/index.html" and "notes/c/index.html"
    When the site is reconciled as a dry run with the plugin "newsletter" and only "wiki/page/"
    Then the orphan pages are exactly "wiki/page/a/index.html" and "wiki/page/b/index.html"

  Scenario: The command line reads the plugin list from the site configuration
    Given an amplify_outputs.json that publishes the plugin "newsletter"
    When the projection environment is built without a PAPYRUS_PLUGINS override
    Then PAPYRUS_PLUGINS is "newsletter"

  Scenario: An explicit PAPYRUS_PLUGINS override takes precedence
    Given an amplify_outputs.json that publishes the plugin "newsletter"
    When the projection environment is built with PAPYRUS_PLUGINS set to "signup"
    Then PAPYRUS_PLUGINS is "signup"

  Scenario: A reconcile refuses when the local plugin list differs from the deployed one
    Given an amplify_outputs.json that publishes the plugin "newsletter"
    When the command line reconciles with PAPYRUS_PLUGINS set to "signup"
    Then the command exits with an error that says the plugin list differs from the deployed one
    And no content is read

  Scenario: A reconcile refuses when the deployed plugin list is unknown
    Given no amplify_outputs.json
    When the command line reconciles with PAPYRUS_PLUGINS set to "newsletter"
    Then the command exits with an error that says the plugin list cannot be checked
    And no content is read
