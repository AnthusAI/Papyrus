Feature: A Papyrus site gets a pull request when a new Papyrus release is out
  Every Papyrus site pins one Papyrus version in many places: both package.json files, both lockfiles, infra/site.json, the Python
  requirement, docs and tests. A scheduled workflow in each site calls the reusable workflow bump-consumer.yml, which runs
  infra/pipeline/bump_consumer.py. The script finds the newest version published on both PyPI and npm, rewrites every line that
  pins the current version, refreshes the lockfiles and opens "chore: bump Papyrus to X" with the release notes. A deploy can add only
  one DynamoDB index to a table, so when the jump changes more than one index on any existing table the pull request is a draft that
  says which tables need the bump staged. The script never merges anything.

  Scenario: A site that is already current gets no pull request
    Given a site pinned to Papyrus 1.2.0
    And PyPI and npm both publish 1.2.0 as their newest release
    When the bump runs
    Then no branch is pushed and no pull request is opened

  Scenario: The newest release on both registries is the target
    Given a site pinned to Papyrus 1.0.0
    And PyPI publishes up to 1.2.0 and npm publishes up to 1.3.0
    When the bump runs
    Then a pull request titled "chore: bump Papyrus to 1.2.0" is opened against the integration branch

  Scenario: Every line that pins the current version moves, and other versions are left alone
    Given a site pinned to Papyrus 1.0.0
    And PyPI and npm both publish 1.1.0 as their newest release
    When the bump runs
    Then infra/site.json, package.json, infra/package.json, requirements.txt and README.md pin 1.1.0
    And a comment about an earlier Papyrus 0.9.0 change still says 0.9.0
    And a line that pins 1.0.0 but does not name Papyrus still says 1.0.0

  Scenario: The pull request lists the releasing changes between the versions
    Given a site pinned to Papyrus 1.0.0
    And PyPI and npm both publish 1.1.0 as their newest release
    When the bump runs
    Then the pull request body lists "feat: forum posts reach the edge"
    And the pull request body does not list "docs: reword the guide"

  Scenario: One new index on a table is a normal pull request
    Given a site pinned to Papyrus 1.0.0
    And PyPI and npm both publish 1.1.0 as their newest release
    When the bump runs
    Then the pull request is not a draft
    And the pull request body says one deploy can carry the bump

  Scenario: Two new indexes on one existing table make a draft that names the table
    Given a site pinned to Papyrus 1.0.0
    And PyPI and npm both publish 1.2.0 as their newest release
    When the bump runs
    Then the pull request is a draft
    And the pull request body names the table "Reference" as needing a staged bump
    And the pull request body does not name the table "Brand" as needing a staged bump

  Scenario: A dry run reports and changes nothing
    Given a site pinned to Papyrus 1.0.0
    And PyPI and npm both publish 1.2.0 as their newest release
    When the bump is dry-run
    Then no branch is pushed and no pull request is opened
    And infra/site.json still pins 1.0.0
