@checklist-gate
Feature: The human review stamp is read from the checklist of the lineage being published or announced
  A lineage's human review stamp is its review step done against its current version: the review of readers (review_people) for a Story written in the
  newsroom or an imported Story, and human_review for a translation, whose own lineage (`<story>--<language>`) has its own checklist. The stamp of a
  translation is read from the translation's rows, never from the original's, so a review of the English Story says nothing about the Spanish one. The
  publish gate of a translation and every announcement that requires a reviewed source read the stamp the same way.

  A person records the review. An agent closes a review step (done, skipped or not applicable) only on a person's recorded instruction: the person and
  their own words, kept with the change, and the stamp then names that person as delegated. An agent alone is refused with `delegation-required` and the
  step stays open. A review is of one version: an edit makes a new version, which has no stamp until the step is done again. Everything here runs on the
  in-memory backend; nothing calls AWS or a model.

  # --- a Story written in the newsroom ------------------------------------------------------------------------------------------------------------

  Scenario: A person's review is the Story's stamp on the version they reviewed
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step review_people --state done --note 'Read it through as a reader' --actor-label Ryan"
    Then the procedure command succeeded
    And the lineage "story-1" has a human review stamp on version 1 by "Ryan"

  Scenario: An agent alone cannot tick the review of readers
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step review_people --state done --note 'Looks fine to me' --agent Claude"
    Then the procedure command was refused saying "delegation-required"
    And the checklist item "review_people" is "open"
    And the lineage "story-1" has no human review stamp on version 1

  Scenario: An agent alone cannot skip the review of readers either
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step review_people --state skipped --reason 'Short post' --agent Claude"
    Then the procedure command was refused saying "delegation-required"
    And the checklist item "review_people" is "open"

  Scenario: An agent ticks the review on a person's recorded instruction, and the stamp is delegated and names the person
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step review_people --state done --note 'Ryan read it on his phone' --agent Claude --on-instruction-of Ryan --quote 'I read it, mark the review done'"
    Then the procedure command succeeded
    And the checklist item "review_people" was changed by the agent "Claude"
    And the checklist item "review_people" records the instruction of "Ryan" saying "I read it, mark the review done"
    And the lineage "story-1" has a delegated human review stamp on version 1 naming "Ryan" and the agent "Claude"
    When I run "stories next" with "--story story-1"
    Then the procedure output mentions "agent:Claude on the instruction of Ryan"

  Scenario: An agent's instruction needs the person's words, not only their name
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step review_people --state done --note 'Read it' --agent Claude --on-instruction-of Ryan"
    Then the procedure command was refused saying "delegation-required"
    And the checklist item "review_people" is "open"

  Scenario: An edit after the review drops the stamp until the review is done again
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the review step "review_people" is done with the note "Read it through"
    When I run "stories save-version" with "--story story-1 --body 'A rewritten second paragraph' --reason edit --author-label Ryan --no-check"
    Then the lineage "story-1" has a human review stamp on version 1 by "Editor"
    And the lineage "story-1" has no human review stamp on version 2
    When I run "stories step" with "--story story-1 --step review_people --state done --note 'Read the rewrite' --actor-label Ryan"
    Then the lineage "story-1" has a human review stamp on version 2 by "Ryan"

  # --- an imported Story --------------------------------------------------------------------------------------------------------------------------

  Scenario: An imported Story's review is not ticked by an agent alone, so it does not publish
    Given a Story at the "copywriting" stage
    When the Story is imported from "articles/hello.md"
    And I run "stories step" with "--story story-1 --step review_people --state done --note 'Imported copy reads fine' --agent Claude"
    Then the procedure command was refused saying "delegation-required"
    When the Story is published by an editor
    Then publishing was refused with the code "checklist-open" saying "Reviewed for readers (review_people)"
    And the lineage "story-1" has no human review stamp on version 1

  Scenario: An imported Story ticked by an agent on a person's instruction publishes with a delegated stamp
    Given a Story at the "copywriting" stage
    When the Story is imported from "articles/hello.md"
    And I run "stories step" with "--story story-1 --step review_people --state done --note 'Ana checked it against the source' --agent Claude --on-instruction-of Ana --quote 'Checked it, it can go'"
    Then the procedure command succeeded
    And the lineage "story-1" has a delegated human review stamp on version 1 naming "Ana" and the agent "Claude"
    When the Story is published by an editor
    Then publishing succeeded

  Scenario: An imported Story a person reviewed has that person's stamp
    Given a Story at the "copywriting" stage
    When the Story is imported from "articles/hello.md"
    And I run "stories step" with "--story story-1 --step review_people --state done --note 'Read it against its source' --actor-label Ana"
    Then the lineage "story-1" has a human review stamp on version 1 by "Ana"

  # --- a translation ------------------------------------------------------------------------------------------------------------------------------

  Scenario: A translation's stamp is read from its own lineage, not from the original's
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And a scripted translator, judge and repairer for "es-419"
    And an editor asked for the "es-419" translation of "story-waymo"
    And the English Story is served by a site that publishes Spanish under "es"
    And the translation run for "es-419" has finished
    When a person records the review of the English Story's version 3
    Then the lineage "story-waymo" has a human review stamp on version 3 by "An Editor"
    And the lineage "story-waymo--es-419" has no human review stamp on version 1
    When a person records the review of the translation with the note "Read it against the English; it reads naturally"
    Then the lineage "story-waymo--es-419" has a human review stamp on version 1 by "An Editor"

  Scenario: An agent alone cannot tick a translation's review, so the translation does not publish
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And a scripted translator, judge and repairer for "es-419"
    And an editor asked for the "es-419" translation of "story-waymo"
    And the English Story is served by a site that publishes Spanish under "es"
    And the translation run for "es-419" has finished
    When the agent "Claude" marks the translation's review done with the note "Reads naturally"
    Then the review is refused as "delegation-required"
    And the translation's checklist item "human_review" is "open"
    When a person publishes the translation
    Then publishing is refused as "checklist-open" naming "human_review"

  Scenario: An agent ticks a translation's review on a person's instruction, and it publishes with a delegated stamp
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And a scripted translator, judge and repairer for "es-419"
    And an editor asked for the "es-419" translation of "story-waymo"
    And the English Story is served by a site that publishes Spanish under "es"
    And the translation run for "es-419" has finished
    When the agent "Claude" marks the translation's review done on the instruction of "Lucia" saying "Lo leí, está bien"
    Then the lineage "story-waymo--es-419" has a delegated human review stamp on version 1 naming "Lucia" and the agent "Claude"
    When a person publishes the translation
    Then the translation is published as "story-waymo--es-419" at "es/articles/bajan-los-choques-de-waymo/index.html"

  Scenario: A correction after the review drops the translation's stamp
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And a scripted translator, judge and repairer for "es-419"
    And an editor asked for the "es-419" translation of "story-waymo"
    And the English Story is served by a site that publishes Spanish under "es"
    And the translation run for "es-419" has finished
    And a person records the review of the translation with the note "Read it against the English; it reads naturally"
    When a person named "Pat Editor" corrects "abarca" to "cubre" in the "es-419" translation because "the verb reads better"
    Then the lineage "story-waymo--es-419" has a human review stamp on version 1 by "An Editor"
    And the lineage "story-waymo--es-419" has no human review stamp on version 2
