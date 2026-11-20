Feature: A deploy registers every core and site procedure, and a published version never drifts from Git
  Procedures live in Git: the fifteen core procedures in the wheel (each declares its kind on its first line and is listed in
  papyrus-required-procedures.json, together with its title, category, description and parameter schema), and a site's own procedures in
  the site's repository, listed in the site's papyrus-site-procedures.json. The Amplify build of a site runs `papyrus procedures
  seed-required` after the backend deploys, as the build role, so every procedure is registered as a published version in the site's
  backend with no step done by hand. A version's id carries a digest of the source, so the same source is never written twice: an
  unchanged procedure writes nothing, a changed one publishes a new version and archives the old one. `--dry-run` reads the backend and
  says what would change; `--check` reads it and stops with an error when anything differs from Git. Nothing falls back: an unknown
  kind, a missing file, a missing kind line or a site kind that takes a core kind's name stops the step with a clear error.

  Scenario: A deploy to a site with nothing registered creates every core procedure
    Given a site backend with no procedures registered
    When the deploy registers the core procedures
    Then all 16 core kinds are published with a version whose id carries the digest of the packaged source and its metadata
    And each definition carries the title, category and description from the registry's metadata
    And each version carries the parameter schema and defaults from the registry's metadata

  Scenario: A deploy of unchanged procedures writes nothing
    Given a site backend where the core procedures were registered by an earlier deploy
    When the deploy registers the core procedures again
    Then every kind is reported unchanged
    And nothing was written to the backend

  Scenario: A changed procedure publishes a new version and archives the old one
    Given a site backend where the core procedures were registered by an earlier deploy
    And the source of the kind "newsroom.editor" differs from what is published
    When the deploy registers the core procedures
    Then the kind "newsroom.editor" is reported registered as version 2 and the other 15 are unchanged
    And the first version of "newsroom.editor" is archived and the definition points at the new version

  Scenario: A procedure registered before kind headers existed moves to a digest version
    Given a site backend holding the starter version "procedure-version-newsroom-research-explorer-1" of "newsroom.research.explorer"
    When the deploy registers the core procedures
    Then the kind "newsroom.research.explorer" is reported registered as version 2
    And the starter version is archived

  Scenario: A dry run reads the backend, says what would change and writes nothing
    Given a site backend where the core procedures were registered by an earlier deploy
    And the source of the kind "newsroom.editor" differs from what is published
    When the deploy plans the core procedures without applying them
    Then the kind "newsroom.editor" is reported changed and the other 15 are reported unchanged
    And nothing was written to the backend

  Scenario: A drift check passes when every published version matches Git
    Given a site backend where the core procedures were registered by an earlier deploy
    When the drift check runs
    Then the check passes

  Scenario: A drift check fails and names every procedure that differs from Git
    Given a site backend where the core procedures were registered by an earlier deploy
    And the source of the kind "newsroom.editor" differs from what is published
    And the kind "story.localize" has never been registered
    When the drift check runs
    Then the check fails and names "newsroom.editor" as changed and "story.localize" as missing
    And nothing was written to the backend

  Scenario: A site's own procedure is registered with its skills, beside the core ones
    Given a site repository that lists the kind "example.ruling-analysis" in its papyrus-site-procedures.json
    When the deploy registers the core procedures and the site's procedures
    Then the kind "example.ruling-analysis" is published under the category "site"
    And all 16 core kinds are published

  Scenario: A site kind that takes a core kind's name is refused
    Given a site repository that lists the kind "newsroom.editor" in its papyrus-site-procedures.json
    When the deploy registers the core procedures and the site's procedures
    Then the deploy stops and says the site kind "newsroom.editor" shadows a core kind
    And nothing was written to the backend

  Scenario: A site may replace a core kind only when it says so
    Given a site repository that lists the kind "newsroom.editor" and names it under "overrides"
    When the deploy registers the core procedures and the site's procedures
    Then the kind "newsroom.editor" is published from the site's source on the core definition
    And the core source of "newsroom.editor" is not written

  Scenario: A site file that declares another kind is refused
    Given a site repository whose file for "example.ruling-analysis" declares the kind "example.other"
    When the deploy registers the core procedures and the site's procedures
    Then the deploy stops and says the file declares "example.other", not "example.ruling-analysis"

  Scenario: A site file that is not there stops the deploy
    Given a site repository that lists the kind "example.ruling-analysis" with a file that does not exist
    When the deploy registers the core procedures and the site's procedures
    Then the deploy stops and names the missing file

  Scenario: A core kind without metadata is caught by the registry check
    Given a registry of two kinds, each with a file that declares it
    When the registry loses the metadata of the first kind
    Then the check names the first kind as having no metadata

  Scenario: Metadata for a kind the registry does not list is caught
    Given a registry of two kinds, each with a file that declares it
    When the registry gains metadata for a kind it does not list
    Then the check names that kind as metadata for an unregistered kind
