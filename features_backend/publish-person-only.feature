@pod @checklist-gate
Feature: Nothing publishes by itself when no person has reviewed it: pod-loaded, imported and translated Stories publish only by a person's hand
  Three kinds of Story reach the publish step without the review a Story written in the newsroom goes through. A Story loaded from a pod carries only the pod's
  claims, which are lines of text anyone can type. An imported Story has a checklist whose every step but publishing is marked not applicable. A translation is
  written by a machine and has no steps to tick. Until each language has its own checklist that publishing checks (PPY-473f8f), one rule keeps all three
  from publishing automatically: the publish step refuses any publish of one of them that is not a person's own act, with the code
  `person-publish-required` and words that say how to proceed. Nothing is forced and nothing falls back. A pod load therefore leaves the Story a draft and
  reports the refusal; automatic translation, a schedule and an agent leave a ready draft. A person publishing by hand, in the console or with the CLI signed
  in as themselves, is not stopped by this rule, and every other rule (the checklist, the rating, the site's approval) still applies to them. A Page or a
  wiki page has no checklist to skip, so the rule does not touch it. Every scenario runs against a fake newsroom and a fake page build.

  Background:
    Given a signed-in newsroom with no stories
    And a started pod
    And the pod has a "web" folder of site settings

  Scenario: A pod load's publish of a Story is refused with a way to proceed and the Story stays a draft
    Given the pod file "slow-water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0091
      type: papyrus:Article
      title: Slow water
      stage: published
      ---
      Slow water keeps rain on the land a little longer.
      """
    And the pod is a git repository with everything committed
    When I load the pod with "papyrus pod load POD"
    Then the pod command exits with status 0
    And the pod report says "slow-water.md: refused [person-publish-required]"
    And the pod report says "publish it by hand"
    And the pod report says "0 published, 1 refused"
    And the story for the note "slow-water.md" is a draft that is not live
    And the site's page build was asked for 0 times

  Scenario: An automation's publish of a pod-loaded Story is refused even when the site needs no approval
    Given the pod file "slow-water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0092
      type: papyrus:Article
      title: Slow water
      stage: copywriting
      ---
      Slow water keeps rain on the land a little longer.
      """
    And the pod is a git repository with everything committed
    And the pod is loaded
    When an automation publishes the story for the note "slow-water.md"
    Then the publish was refused with the code "person-publish-required"
    And the publish was refused saying "publish it by hand"

  Scenario: A person's publish of a pod-loaded Story is not stopped by this rule, only by the rules every publish meets
    Given the pod file "slow-water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0093
      type: papyrus:Article
      title: Slow water
      stage: copywriting
      ---
      Slow water keeps rain on the land a little longer.
      """
    And the pod is a git repository with everything committed
    And the pod is loaded
    When an editor publishes the story for the note "slow-water.md"
    Then the publish was refused with the code "checklist-open"

  Scenario: A Page loaded from a pod still publishes with the load
    Given the pod file "about.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0094
      type: papyrus:Page
      title: About
      stage: published
      ---
      About this site.
      """
    And the pod is a git repository with everything committed
    When I load the pod with "papyrus pod load POD"
    Then the story for the note "about.md" is published
    And the pod report says "1 published, 0 refused"
