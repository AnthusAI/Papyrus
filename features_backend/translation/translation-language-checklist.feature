@checklist-gate
Feature: Each language of a Story has its own checklist, and publishing a translation checks it
  A translation is a Story lineage of its own (`<story>--<language>`), and it has its own checklist rows beside the English Story's. Its template is
  translate, faithfulness, copy edit, human review and publish. Rating and the cover belong to the original (one rating serves every language), so they
  are not rows of the translation. The translation run that saves a version, a person's imported copy and a person's correction each write the rows they
  can prove: translate, faithfulness and copy edit are recorded for that version, done where the run's records say so. Human review is a person's step.
  It is required where the site's procedure requires the review of readers (`review_people`), which the default procedure does, and a site that makes
  that review optional does not ask for it on a translation either. A review is done against one version of the translation: an edit afterwards drops it.
  Publishing a translation checks the checklist of the lineage being published, at its current version, and refuses with `checklist-open` naming each open
  step and the command that closes it, the same refusal a Story gets. Nothing publishes a translation by itself while a required step is open, so an
  automatic translation stays a ready draft until a person has reviewed it. A translation that has no rows at all (one saved before language checklists)
  is refused the same way. A held translation still needs a person to answer its review request, and the answer is the person's decision about the
  faithfulness finding. Everything here is synthetic: the models are scripted and nothing reaches a network.

  Background:
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And a scripted translator, judge and repairer for "es-419"
    And an editor asked for the "es-419" translation of "story-waymo"
    And the English Story is served by a site that publishes Spanish under "es"

  Scenario: A clean translation's run records the language's steps and leaves the review of a person open
    Given the translation run for "es-419" has finished
    Then the translation's checklist item "translate" is "done"
    And the translation's checklist item "translate" was changed by the system "Automatically, from the translation's records"
    And the translation's checklist item "faithfulness" is "done"
    And the translation's checklist item "copy_edit" is "done"
    And the translation's checklist item "human_review" is "open"
    And the translation's checklist item "publish" is "open"
    And the translation's checklist has no item for "rated" or "illustration"

  Scenario: A clean translation is refused until a person has reviewed it
    Given the translation run for "es-419" has finished
    When a person publishes the translation
    Then publishing is refused as "checklist-open" naming "Reviewed by a person (human_review)"
    And publishing is refused naming the command "papyrus stories step --story story-waymo--es-419"
    And the translation is still a ready draft
    And no Spanish page is served

  Scenario: A person's review lets a clean translation publish
    Given the translation run for "es-419" has finished
    When a person records the review of the translation with the note "Read it against the English; it reads naturally"
    And a person publishes the translation
    Then the translation is published as "story-waymo--es-419" at "es/articles/bajan-los-choques-de-waymo/index.html"
    And the translation's checklist item "human_review" is "done"
    And the translation's checklist item "publish" is "done"

  Scenario: An automatic publish of a clean translation is refused and leaves a ready draft
    Given the translation run for "es-419" has finished
    When an automation publishes the translation
    Then publishing is refused as "checklist-open" naming "human_review"
    And the translation is still a ready draft
    And no Spanish page is served
    When a person records the review of the translation with the note "Read it against the English; it reads naturally"
    And a person publishes the translation
    Then the translation is published as "story-waymo--es-419" at "es/articles/bajan-los-choques-de-waymo/index.html"

  Scenario: A site that makes the review of readers optional does not ask for it on a translation
    Given the site does not require a person's review of its translations
    And the translation run for "es-419" has finished
    When a person publishes the translation
    Then the translation is published as "story-waymo--es-419" at "es/articles/bajan-los-choques-de-waymo/index.html"
    And the translation's checklist item "human_review" is "open"

  Scenario: A site that says its translations need no person's review publishes them on the run's checks, though originals still need one
    Given the site requires its readers' review of an original but says its translations need no person's review
    And the translation run for "es-419" has finished
    When a person publishes the translation
    Then the translation is published as "story-waymo--es-419" at "es/articles/bajan-los-choques-de-waymo/index.html"
    And the translation's checklist item "human_review" is "open"

  Scenario: A held translation records the open faithfulness step and still needs a person's answer and a person's review
    Given the translator writes "varias ciudades" where the English says "12 cities"
    And the repairer keeps the wrong wording
    And the translation run for "es-419" has finished held
    Then the translation's checklist item "translate" is "done"
    And the translation's checklist item "faithfulness" is "open"
    When a person publishes the translation
    Then publishing is refused as "translation-held" naming the review request
    When a person answers the review request with "approve"
    And a person publishes the translation
    Then publishing is refused as "checklist-open" naming "human_review"
    When a person records the review of the translation with the note "The held wording was fixed by hand and checked"
    And a person publishes the translation
    Then the translation is published as "story-waymo--es-419" at "es/articles/bajan-los-choques-de-waymo/index.html"

  Scenario: A review recorded for an earlier version does not count after a person's correction
    Given the translation run for "es-419" has finished
    And a person records the review of the translation with the note "Read it against the English; it reads naturally"
    When a person named "Pat Editor" corrects "abarca" to "cubre" in the "es-419" translation because "the verb reads better"
    Then the translation's checklist item "translate" is "done" for version 2
    And the translation's checklist item "copy_edit" is "done" for version 2
    When a person publishes the translation
    Then publishing is refused as "checklist-open" naming "done for version 1, this is version 2"
    When a person records the review of the translation with the note "Read the corrected wording"
    And a person publishes the translation
    Then the translation is published as "story-waymo--es-419" at "es/articles/bajan-los-choques-de-waymo/index.html"

  Scenario: Finished copy a person imported gets its own rows and waits for a person's review
    Given the translation run for "es-419" has finished
    And a person records the review of the translation with the note "Read the machine's version"
    And finished Spanish copy for "story-waymo" written for the "es-419" edition
    And the copy has no picture, as the English page of this site has none
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft, reviewed by the Madrid editors"
    Then the import is saved, not held
    And the translation's checklist item "translate" is "done"
    And the translation's checklist item "translate" has evidence naming "written by Ana Writer"
    And the translation's checklist item "copy_edit" is "done" for version 2
    When a person publishes the translation
    Then publishing is refused as "checklist-open" naming "done for version 1, this is version 2"

  Scenario: A translation saved before language checklists has no rows and is refused naming its required steps
    Given the translation run for "es-419" has finished
    And the translation's checklist rows are removed, as for a translation saved before language checklists
    When a person publishes the translation
    Then publishing is refused as "checklist-open" naming "Translated (translate)"
    And publishing is refused naming the command "papyrus stories step --story story-waymo--es-419"

  Scenario: A person marks a step of the translation's own checklist from the command line
    Given the translation run for "es-419" has finished
    When a person marks the translation's step "human_review" done with the note "Read it against the English; it reads naturally"
    Then the translation's checklist item "human_review" is "done"
    And the translation's checklist item "human_review" was changed by the person "An Editor"
