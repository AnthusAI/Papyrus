@pod @checklist-gate
Feature: A pod with no site is private, and its load never publishes
  A pod belongs to a site only when it has a `web/` folder with the site's settings, `web/projection.json`. Every other pod is private. `papyrus pod build`
  refuses a private pod and builds nothing. `papyrus pod load` loads a private pod's notes as private newsroom data at their stage and never publishes: a
  note at `stage: published` is recorded at that stage, a draft Story with no page, and the load says that nothing was published. A pod with a site
  loads the same way and then publishes a note that says published through the newsroom's publish step (features_backend/pods/pod-load-publish.feature), which has its own gates.

  Background:
    Given a signed-in newsroom with no stories
    And a started pod
    And the pod file "slow-water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0061
      type: papyrus:Article
      title: Slow water
      stage: published
      ---
      Slow water keeps rain on the land a little longer.
      """
    And the pod file "idea.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0062
      type: papyrus:Post
      title: An idea
      stage: idea
      ---
      Maybe.
      """

  Scenario: Building a private pod is refused
    Given the pod is a git repository with everything committed
    When I run the pod command "papyrus pod build POD"
    Then the pod command exits with status 2
    And the pod command fails with the message "is a private pod"
    And the pod command fails with the message "nothing is built or published"
    And no site, network or sign-in was touched

  Scenario: A private pod loads every note at its stage as private newsroom data
    Given the pod is a git repository with everything committed
    When I load the pod with "papyrus pod load POD"
    Then the pod command exits with status 0
    And the pod report says "kind: private pod"
    And the story for the note "idea.md" has the stage "idea"
    And the story for the note "slow-water.md" has the stage "published"

  Scenario: A load never publishes, even a note whose stage is published
    Given the pod is a git repository with everything committed
    When I load the pod with "papyrus pod load POD"
    Then the story for the note "slow-water.md" is a draft that is not live
    And no story is published
    And the load output says "nothing was published"

  Scenario: A note with no stage loads at copywriting
    Given the pod file "plain.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0063
      type: papyrus:Page
      title: Plain
      ---
      A page.
      """
    And the pod is a git repository with everything committed
    When I load the pod with "papyrus pod load POD"
    Then the story for the note "plain.md" has the stage "copywriting"
    And no story is published

  Scenario: A pod with a site is built by the site's own build, not refused as private
    Given the pod has a "web" folder of site settings
    And the pod is a git repository with everything committed
    When I run the pod command "papyrus pod build POD"
    Then the pod report does not say "is a private pod"

  Scenario: A pod with a site loads a published Article, and the publish step refuses it while its checklist is open
    Given the pod has a "web" folder of site settings
    And the pod is a git repository with everything committed
    When I load the pod with "papyrus pod load POD"
    Then the pod command exits with status 0
    And the pod report says "kind: site pod (web/projection.json)"
    And the pod report says "refused [checklist-open]"
    And no story is published
