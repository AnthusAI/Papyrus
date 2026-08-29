@cli @operator
Feature: Operator CLI
  As a Papyrus operator
  I want one `papyrus` command with the same verbs against local pod or cloud backends
  So I can list references and work without PYTHONPATH hacks or parallel tool trees.

  Background:
    Given the operator CLI fixture root is available

  # ---------------------------------------------------------------------------
  # Entry, install, and help
  # ---------------------------------------------------------------------------

  @help
  Scenario: Bare group names print subcommand help instead of a bare error
    When I run `papyrus references`
    Then the exit code should be 0
    And stderr should be empty
    And stdout should list the available `references` subcommands
    And stdout should mention `list` and `show`

    When I run `papyrus assignments`
    Then the exit code should be 0
    And stderr should be empty
    And stdout should list the available `assignments` subcommands
    And stdout should mention `list`

    When I run `papyrus auth`
    Then the exit code should be 0
    And stderr should be empty
    And stdout should list the available `auth` subcommands
    And stdout should mention `refresh`

    When I run `papyrus knowledge`
    Then the exit code should be 0
    And stderr should be empty
    And stdout should list the available `knowledge` subcommands

  @help
  Scenario: Top-level help documents operator groups without requiring PYTHONPATH
    When I run `papyrus --help`
    Then the exit code should be 0
    And stdout should mention `references`, `assignments`, `auth`, and `knowledge`
    And stdout should explain that backend selection comes from project config or `--backend`

  @install
  Scenario: Installed entrypoint runs without PYTHONPATH
    When I run `papyrus --version` from a clean environment without PYTHONPATH
    Then the exit code should be 0
    And stderr should not contain "ImportError"
    And stderr should not contain "ModuleNotFoundError"

  # ---------------------------------------------------------------------------
  # Backend selection
  # ---------------------------------------------------------------------------

  @backend
  Scenario Outline: Backend comes from config with optional override
  # Operators should not learn a second command tree for local pod work.
    Given operator CLI config selects backend "<configured_backend>"
    When I run `papyrus references list --limit 1`
    Then the exit code should be 0
    And stdout should report backend "<configured_backend>"

    When I run `papyrus references list --backend <override_backend> --limit 1`
    Then the exit code should be 0
    And stdout should report backend "<override_backend>"

    Examples:
      | configured_backend | override_backend |
      | local              | cloud            |
      | cloud              | local            |

  @backend
  Scenario: Invalid backend values fail with operator guidance
    When I run `papyrus references list --backend nowhere`
    Then the exit code should be 2
    And stderr should contain "unknown backend"
    And stderr should mention `local` and `cloud`
    And stderr should not contain a Python traceback

  # ---------------------------------------------------------------------------
  # Config defaults (corpus, publication, endpoint)
  # ---------------------------------------------------------------------------

  @config
  Scenario: references list uses publication corpus default without --corpus-key
    Given operator CLI config selects backend "cloud"
    And operator CLI config sets default corpus key "threat-intelligence"
    When I run `papyrus references list --limit 3`
    Then the exit code should be 0
    And stdout should report corpus key "threat-intelligence"
    And stdout should not require `--corpus-key` on the command line

  @config
  Scenario: --corpus-key overrides the configured default
    Given operator CLI config selects backend "cloud"
    And operator CLI config sets default corpus key "threat-intelligence"
    When I run `papyrus references list --corpus-key AI-ML-research --limit 1`
    Then the exit code should be 0
    And stdout should report corpus key "AI-ML-research"

  # ---------------------------------------------------------------------------
  # references list — cloud backend
  # ---------------------------------------------------------------------------

  @references @cloud-backend
  Scenario: Cloud references list uses tabular operator output
    Given operator CLI config selects backend "cloud"
    And the cloud references fixture is loaded
    When I run `papyrus references list --limit 2 --order newest`
    Then the exit code should be 0
    And stdout should be tabular operator output
    And stdout header should include columns:
      | column   |
      | kind     |
      | status   |
      | id       |
      | title    |
      | corpus   |
      | url      |
    And stdout row kind should be "cloud-reference"
    And stdout should contain reference id "ref-cloud-001"
    And stdout should contain reference id "ref-cloud-002"

  @references @cloud-backend
  Scenario: Cloud references list honors filters shared with local backend
    Given operator CLI config selects backend "cloud"
    And the cloud references fixture is loaded
    When I run `papyrus references list --status accepted --limit 10`
    Then the exit code should be 0
    And every listed reference should have status "accepted"

  # ---------------------------------------------------------------------------
  # references list — local pod backend
  # ---------------------------------------------------------------------------

  @references @local-backend
  Scenario: Local pod references list uses the same argv and output contract
    Given operator CLI config selects backend "local"
    And the local pod fixture "anthus-blog" is configured
    When I run `papyrus references list --limit 2 --order newest`
    Then the exit code should be 0
    And stdout should be tabular operator output
    And stdout header should include columns:
      | column   |
      | kind     |
      | status   |
      | id       |
      | title    |
      | corpus   |
      | url      |
    And stdout row kind should be "pod-reference"
    And stdout should contain reference id "ref-pod-001"
    And stdout should contain reference id "ref-pod-002"
    And stdout should read pod artifacts from the Kanbus project
    And stdout should not read a revived local Markdown content store

  @references @local-backend
  Scenario: Local pod references list honors the same filters as cloud
    Given operator CLI config selects backend "local"
    And the local pod fixture "anthus-blog" is configured
    When I run `papyrus references list --status accepted --limit 10`
    Then the exit code should be 0
    And every listed reference should have status "accepted"

  # ---------------------------------------------------------------------------
  # references show
  # ---------------------------------------------------------------------------

  @references @cloud-backend
  Scenario: Cloud references show prints one record
    Given operator CLI config selects backend "cloud"
    And the cloud references fixture is loaded
    When I run `papyrus references show ref-cloud-001`
    Then the exit code should be 0
    And stdout should be a single reference detail block
    And stdout should report kind "cloud-reference"
    And stdout should report id "ref-cloud-001"

  @references @local-backend
  Scenario: Local pod references show prints one record with the same shape
    Given operator CLI config selects backend "local"
    And the local pod fixture "anthus-blog" is configured
    When I run `papyrus references show ref-pod-001`
    Then the exit code should be 0
    And stdout should be a single reference detail block
    And stdout should report kind "pod-reference"
    And stdout should report id "ref-pod-001"
    And stdout should report url "https://example.com/articles/compaction-cliff"
    And stdout should report why "Canonical accepted fixture for operator CLI list/show."

  @references
  Scenario: Missing references fail with operator guidance
    Given operator CLI config selects backend "cloud"
    And the cloud references fixture is loaded
    When I run `papyrus references show missing-reference`
    Then the exit code should be 2
    And stderr should contain "not found"
    And stderr should not contain a Python traceback

  # ---------------------------------------------------------------------------
  # assignments list — distinguish newsroom work from pod stories
  # ---------------------------------------------------------------------------

  @assignments @cloud-backend
  Scenario: Cloud assignments list shows GraphQL Assignment work records
    Given operator CLI config selects backend "cloud"
    And the cloud assignments fixture is loaded
    When I run `papyrus assignments list --limit 2`
    Then the exit code should be 0
    And stdout should be tabular operator output
    And stdout header should include columns:
      | column   |
      | kind     |
      | status   |
      | id       |
      | type     |
      | title    |
    And stdout row kind should be "newsroom-assignment"
    And stdout should contain assignment id "asg-cloud-001"
    And stdout should not label any row as a pod story

  @assignments @local-backend
  Scenario: Local pod assignments list shows Kanbus stories, not GraphQL Assignments
    Given operator CLI config selects backend "local"
    And the local pod fixture "anthus-blog" is configured
    When I run `papyrus assignments list --limit 2`
    Then the exit code should be 0
    And stdout should be tabular operator output
    And stdout header should include columns:
      | column   |
      | kind     |
      | status   |
      | id       |
      | type     |
      | title    |
    And stdout row kind should be "pod-story"
    And stdout should contain story id "ANTH-33c4de"
    And stdout should not label any row as a newsroom-assignment
    And stdout help context should direct board work to `kbs`

  @assignments
  Scenario: assignments list documents the object-kind distinction in help
    When I run `papyrus assignments --help`
    Then the exit code should be 0
    And stdout should explain that cloud rows are GraphQL Assignment records
    And stdout should explain that local rows are Kanbus pod stories
    And stdout should state that `kbs` owns board columns and transitions

  # ---------------------------------------------------------------------------
  # Auth
  # ---------------------------------------------------------------------------

  @auth @cloud-backend
  Scenario: auth refresh mints a JWT without a traceback
    Given operator CLI config selects backend "cloud"
    And cloud auth fixtures can mint a JWT
    When I run `papyrus auth refresh --write-env <tmp-env>`
    Then the exit code should be 0
    And stderr should be empty
    And stdout should confirm the JWT was written
    And the file "<tmp-env>" should contain `PAPYRUS_GRAPHQL_JWT`

  @auth @cloud-backend
  Scenario: Expired JWT surfaces operator guidance instead of a traceback
    Given operator CLI config selects backend "cloud"
    And the cloud references fixture is loaded
    And `PAPYRUS_GRAPHQL_JWT` is expired
    When I run `papyrus references list --limit 1`
    Then the exit code should be 2
    And stderr should mention `papyrus auth refresh`
    And stderr should not contain "Traceback"
    And stderr should not contain "ValueError: PAPYRUS_GRAPHQL_JWT is expired"

  @auth @local-backend
  Scenario: Local pod backend does not require cloud JWT for references list
    Given operator CLI config selects backend "local"
    And the local pod fixture "anthus-blog" is configured
    And `PAPYRUS_GRAPHQL_JWT` is missing
    When I run `papyrus references list --limit 1`
    Then the exit code should be 0
    And stderr should not mention `papyrus auth refresh`

  # ---------------------------------------------------------------------------
  # Parity contract
  # ---------------------------------------------------------------------------

  @parity
  Scenario: Local and cloud backends accept the same operator flags for references list
    Given the local pod fixture "anthus-blog" is configured
    And the cloud references fixture is loaded
    When I compare accepted flags for `papyrus references list`
    Then local and cloud should accept the same flags:
      | flag          |
      | --limit       |
      | --status      |
      | --order       |
      | --corpus-key  |
      | --backend     |

  @parity
  Scenario: Local and cloud backends accept the same operator flags for assignments list
    Given the local pod fixture "anthus-blog" is configured
    And the cloud assignments fixture is loaded
    When I compare accepted flags for `papyrus assignments list`
    Then local and cloud should accept the same flags:
      | flag      |
      | --limit   |
      | --status  |
      | --type    |
      | --backend |

  # ---------------------------------------------------------------------------
  # Local pod references register — Researcher first-pass dogfood fixes
  # ---------------------------------------------------------------------------

  @references @local-backend @register
  Scenario: Re-registering the same URL refuses instead of overwriting accepted metadata
    Given operator CLI config selects backend "local"
    And the writable local pod fixture "anthus-blog" is configured
    And local pod story "ANTH-33c4de" has an accepted reference for URL "https://example.com/articles/compaction-cliff"
    When I run `papyrus references register --backend local --story ANTH-33c4de --url https://example.com/articles/compaction-cliff --title "Dup probe" --status pending --why "duplicate probe"`
    Then the exit code should be 2
    And stderr should contain "already"
    And stderr should contain "accepted"
    And the local pod reference file for URL "https://example.com/articles/compaction-cliff" should still have status "accepted"

  @references @local-backend @register
  Scenario: Local register requires an explicit story or configured default
    Given operator CLI config selects backend "local"
    And the writable local pod fixture "anthus-blog" is configured without default story
    When I run `papyrus references register --backend local --url https://example.com/new --title "New ref" --status pending --why "probe"`
    Then the exit code should be 2
    And stderr should contain "--story"

    When I run `papyrus references register --backend local --story ANTH-33c4de --url https://example.com/new --title "New ref" --status pending --why "probe"`
    Then the exit code should be 0
    And stdout should mention `stories/ANTH-33c4de/references/`

  @references @local-backend @register
  Scenario: Accepted and pending register reject empty why
    Given operator CLI config selects backend "local"
    And the writable local pod fixture "anthus-blog" is configured
    When I run `papyrus references register --backend local --story ANTH-33c4de --url https://example.com/empty-why --title "Bad ref" --status accepted --why ""`
    Then the exit code should be 2
    And stderr should contain "non-empty --why"

    When I run `papyrus references register --backend local --story ANTH-33c4de --url https://example.com/reject-me --title "Reject ref" --status rejected --why ""`
    Then the exit code should be 0
    And stdout should contain "no pod reference row written"
    And the local pod reference file for URL "https://example.com/reject-me" should not exist

  @references @local-backend @register
  Scenario: project_key changes warn about legacy issue prefixes
    Given operator CLI config selects backend "local"
    And the writable local pod fixture "anthus-blog" is configured
    When I run `papyrus references list --limit 1`
    Then the exit code should be 0
    And stderr should contain "legacy prefix"
    And stderr should mention `WIKI-650fd9`
