Feature: A published Story is translated, checked and polished by one procedure
  The Story translation procedure (`papyrus.story.localize`, PPY-843a7c) translates one published Story into one language per run. It
  translates only the blocks whose source changed, checks every block against the English with the parity rules and a bilingual judge, checks
  it with the language's copy-edit policies, and repairs what it may until a round no longer reduces the findings. Every repair is checked
  against the English again, and one that makes faithfulness worse is undone. Links, citations, code and fixed attributes such as an image's
  credit never reach the model: the system puts them back.

  The result is saved as a new, unpublished version of the Story's sibling lineage (`<story>--<language>`), written by AI, with the source
  version it came from and a provenance record: models, rule versions, findings, rounds and cost. A translation whose meaning still differs
  is held and a review request says why. Nothing waits for a person, nothing is published, and the English Story is never changed except for
  advice about stock phrasing it shares with its translation. The models are scripted here; nothing reaches a network.

  A run starts only from the desired-state record for its Story and language (LocalizationRequest, `{languageGroupId}#{language}`), which
  names the newest published source version to translate. `papyrus stories localize` writes it and starts the site's translation automation;
  the English publish will write the same record. A run for an older source than the record names stops without writing anything, and every
  run records its outcome on the record.

  Background:
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And a scripted translator, judge and repairer for "es-419"
    And an editor asked for the "es-419" translation of "story-waymo"

  Scenario: A clean Story is saved as an unpublished translation with its provenance
    When the translation run for "es-419" runs
    Then the run is saved, not held
    And a version of "story-waymo--es-419" exists written in "es-419" in the language group "story-waymo"
    And that version is unpublished, has no board stage and was written by "AI"
    And it names source version 3 and the source's content hash
    And its provenance names the models, the rule versions, the findings and the cost
    And the English Story's version is unchanged

  Scenario: The translator never sees a link target or an image credit
    When the translation run for "es-419" runs
    Then no text sent to the translator contains "https://example.test/report" or "Jane Doe"
    And the saved translation keeps the link target and the credit exactly as the English has them

  Scenario: A certain repair is applied by code and checked against the English again
    Given the translator writes "86 %" where the English says "68 percent"
    When the translation run for "es-419" runs
    Then the saved translation says "68 %"
    And the run records one round that changed one block
    And the run is saved, not held

  Scenario: Polishing never changes the facts
    Given the translator drops the attribution "the company says"
    And the repairer's rewrite also drops "may"
    When the translation run for "es-419" runs
    Then the rewrite is discarded and the earlier wording kept
    And the run records one reverted block
    And the run is held, and the review request names the dropped attribution

  Scenario: A translation that loses a number is held
    Given the translator writes "varias ciudades" where the English says "12 cities"
    And the repairer keeps the wrong wording
    When the translation run for "es-419" runs
    Then the run is held
    And a flag review request on "story-waymo--es-419" names the missing number
    And the translation is saved unpublished all the same

  Scenario: Running it twice does nothing the second time
    Given the translation run for "es-419" has finished
    When the same run is started again
    Then no model is called
    And no translation version is saved

  Scenario: Only what changed is translated again, and a person's wording is left alone
    Given the translation run for "es-419" has finished
    And a corrector rewrote the translated dek
    When the English Story is republished as version 4 with one paragraph changed and the translation asked for again
    And the translation run for "es-419" runs
    Then exactly one block was sent to the translator
    And the dek is exactly as the corrector wrote it

  Scenario: Stock phrasing is reported back on the English Story
    Given the English Story's second paragraph says "It is worth noting that the report covers 12 cities."
    And the translator keeps the stock phrase as "Cabe destacar que el informe abarca 12 ciudades."
    When the translation run for "es-419" runs
    Then the English Story's version carries advice for "es-419" naming the phrase "It is worth noting"

  Scenario: An outage stops the run and says so, and the next start continues
    Given the judging model cannot be reached
    When the translation run for "es-419" runs
    Then the run fails saying the model service could not be reached
    And no translation is saved
    When the judging model is back and the run starts again
    Then the translator is not called again
    And the run is saved, not held

  Scenario: A cost ceiling holds the run at the end of its round
    Given the translator writes "86 %" where the English says "68 percent"
    And the run's ceiling is already spent by the first translation
    When the translation run for "es-419" runs
    Then the run is held because its cost reached the ceiling
    And no repair round ran

  Scenario: The command writes the request and the run records its outcome on it
    Given nobody asked for a translation
    When an editor asks for the "es-419" translation of "story-waymo"
    Then the request "story-waymo#es-419" names source version 3 and is wanted
    When the translation run for "es-419" runs
    Then the request "story-waymo#es-419" is saved with the run's key

  Scenario: A run with no request translates nothing
    Given nobody asked for a translation
    When the translation run for "es-419" runs
    Then the run stops saying no translation is requested
    And no model is called for it

  Scenario: A run for an older source stops when a newer one is requested
    Given the English Story is republished as version 4 and the translation asked for again
    When a run started for version 3 runs
    Then the run stops saying a newer source is requested
    And no model is called for it

  Scenario: A dry run prints the plan and writes nothing
    Given nobody asked for a translation
    When an editor previews the "es-419" translation of "story-waymo"
    Then the plan lists 5 blocks to translate and the glossary terms the translator will meet
    And no request was written
