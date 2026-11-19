@pod @checklist-gate
Feature: A pod load publishes a Story whose front matter says it is published, through the site's publish step
  A note in a pod with a site that says `stage: published` is published after it is loaded, by the same publish step a person's `papyrus content publish` uses:
  the newsroom's own rules still decide. A closed checklist, a rating where the site requires one, a person's approval where the site requires it and
  every other publish rule apply as they always do, and a load never forces or bypasses one. When a rule refuses, the load reports the refusal for that
  note and the note stays loaded as a draft; the other notes of the load go on. A note that does not say published stays unpublished, a private pod's
  notes are never published, and loading an unchanged file again does nothing. Every scenario runs against a fake newsroom and a fake page build: nothing
  is published on a live site.

  Background:
    Given a signed-in newsroom with no stories
    And a started pod
    And the pod has a "web" folder of site settings

  Scenario: A Page that says it is published is published and its page build is requested
    Given the pod file "about.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0071
      type: papyrus:Page
      title: About
      stage: published
      ---
      About this site.
      """
    And the pod is a git repository with everything committed
    When I load the pod with "papyrus pod load POD"
    Then the pod command exits with status 0
    And the story for the note "about.md" is published
    And the pod report says "about.md: published"
    And the pod report says "1 published, 0 refused"
    And the site's page build was asked for 1 time

  Scenario: A note that does not say published stays unpublished
    Given the pod file "draft.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0072
      type: papyrus:Page
      title: Draft
      stage: copywriting
      ---
      Not yet.
      """
    And the pod file "plain.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0073
      type: papyrus:Page
      title: Plain
      ---
      No stage at all.
      """
    And the pod is a git repository with everything committed
    When I load the pod with "papyrus pod load POD"
    Then the pod command exits with status 0
    And no story is published
    And the site's page build was asked for 0 times
    And the pod report says "nothing was published"

  Scenario: A Story the checklist refuses is reported and stays a draft
    Given the pod file "slow-water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0074
      type: papyrus:Article
      title: Slow water
      stage: published
      ---
      Slow water keeps rain on the land a little longer.
      """
    And the pod is a git repository with everything committed
    When I load the pod with "papyrus pod load POD"
    Then the pod command exits with status 0
    And the pod report says "slow-water.md: refused [checklist-open]"
    And the pod report says "0 published, 1 refused"
    And the story for the note "slow-water.md" is a draft that is not live
    And the site's page build was asked for 0 times

  Scenario: A site that requires a rating refuses a Story a pod only claims is rated
    Given the site requires a rating before publishing
    And the pod file "slow-water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0075
      type: papyrus:Article
      title: Slow water
      stage: published
      rating: 4
      ---
      Slow water keeps rain on the land a little longer.
      """
    And the pod is a git repository with everything committed
    When I load the pod with "papyrus pod load POD"
    Then the pod report says "slow-water.md: refused [checklist-open]"
    And the pod report says "Rate the Story (rated)"
    And no story is published

  Scenario: A site that requires a person's approval refuses a load's publish
    Given the newsroom requires a person's approval before anything publishes
    And the pod file "about.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0076
      type: papyrus:Page
      title: About
      stage: published
      ---
      About this site.
      """
    And the pod is a git repository with everything committed
    When I load the pod with "papyrus pod load POD"
    Then the pod report says "about.md: refused [approval-required]"
    And the story for the note "about.md" is a draft that is not live
    And the site's page build was asked for 0 times

  Scenario: One refused note does not stop the others
    Given the pod file "slow-water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0077
      type: papyrus:Article
      title: Slow water
      stage: published
      ---
      Slow water keeps rain on the land a little longer.
      """
    And the pod file "about.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0078
      type: papyrus:Page
      title: About
      stage: published
      ---
      About this site.
      """
    And the pod is a git repository with everything committed
    When I load the pod with "papyrus pod load POD"
    Then the pod report says "1 published, 1 refused"
    And the story for the note "about.md" is published
    And the story for the note "slow-water.md" is still a draft with no live page

  Scenario: Loading the same pod again does nothing
    Given the pod file "about.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0079
      type: papyrus:Page
      title: About
      stage: published
      ---
      About this site.
      """
    And the pod is a git repository with everything committed
    And the pod is loaded
    When I load the pod again with "papyrus pod load POD"
    Then the pod command exits with status 0
    And nothing was written to the newsroom
    And the site's page build was asked for 0 times
    And the story for the note "about.md" has 1 version

  Scenario: A changed note that says published is saved as a new version and published again
    Given the pod file "about.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0080
      type: papyrus:Page
      title: About
      stage: published
      ---
      About this site.
      """
    And the pod is a git repository with everything committed
    And the pod is loaded
    And the pod file "about.md" has "About this site." replaced by "About this site, a little more."
    And the pod's changes are committed
    When I load the pod again with "papyrus pod load POD"
    Then the story for the note "about.md" has 2 versions
    And the story for the note "about.md" is published
    And the site's page build was asked for 1 time

  Scenario: A dry run says what would be published and writes nothing
    Given the pod file "about.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0081
      type: papyrus:Page
      title: About
      stage: published
      ---
      About this site.
      """
    And the pod is a git repository with everything committed
    When I load the pod with "papyrus pod load POD --dry-run"
    Then the pod report says "about.md: would be published through the site's publish step"
    And nothing was written to the newsroom
    And the site's page build was asked for 0 times

  Scenario: A private pod's note is never published, even when it says published
    Given the pod has no site settings
    And the pod file "about.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0082
      type: papyrus:Page
      title: About
      stage: published
      ---
      About this site.
      """
    And the pod is a git repository with everything committed
    When I load the pod with "papyrus pod load POD"
    Then the pod command exits with status 0
    And no story is published
    And the site's page build was asked for 0 times
