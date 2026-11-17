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
  on a site that translates on publish the English publish writes the same record (story-localize-on-publish.feature), and `papyrus stories localize --all` writes it for every Story that lacks one (story-localize-all.feature). A run for an older source than the record names stops without writing anything, and every
  run records its outcome on the record.

  Background:
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And a scripted translator, judge and repairer for "es-419"
    And an editor asked for the "es-419" translation of "story-waymo"

  Scenario: The blurb and the cover picture alt text are translated with the title and the dek
    Given the English Story also has a blurb and a cover picture alt text
    When the translation run for "es-419" runs
    Then the run is saved, not held
    And the version's blurb and cover picture alt text are the translated ones
    And its picture path and its references stay as written

  Scenario: A clean Story is saved as an unpublished translation with its provenance
    When the translation run for "es-419" runs
    Then the run is saved, not held
    And a version of "story-waymo--es-419" exists written in "es-419" in the language group "story-waymo"
    And that version is unpublished, has no board stage and was written by "AI"
    And it names source version 3 and the source's content hash
    And its provenance names the models, the rule versions, the findings and the cost
    And the English Story's version is unchanged

  Scenario: The translation has its own address, and the original's stored picture
    Given the English Story has the stored picture "assets/waymo.png"
    When the translation run for "es-419" runs
    Then the saved translation's address is "bajan-los-choques-de-waymo" and not the English "waymo-crashes-fall"
    And the saved translation has the stored picture "assets/waymo.png", so it can be published

  Scenario: A later version of the translation keeps its address
    Given the translation run for "es-419" has finished
    When the English Story is republished as version 4 with one paragraph changed and the translation asked for again
    And the translation run for "es-419" runs
    Then the saved translation's address is "bajan-los-choques-de-waymo" and not the English "waymo-crashes-fall"
    And the Spanish lineage has 2 versions

  Scenario: The translator never sees a link target or an image credit
    When the translation run for "es-419" runs
    Then no text sent to the translator contains "https://example.test/report" or "Jane Doe"
    And the saved translation keeps the link target and the credit exactly as the English has them

  Scenario: A translator that damages a link is asked again and the damage is never saved
    Given the translator first answers "El ⟦1⟧informe abarca 12 ciudades." for "The [report]⟦1⟧ covers 12 cities." and is right when asked again
    When the translation run for "es-419" runs
    Then the translator was asked again about the link and told where the target belongs, without being shown the target
    And the saved translation has the link "informe" with its target and no stray address

  Scenario: A certain repair is applied by code and checked against the English again
    Given the translator writes "86 %" where the English says "68 percent"
    When the translation run for "es-419" runs
    Then the saved translation says "68 %"
    And the run records one round that changed one block
    And the run is saved, not held

  Scenario: A site that addresses readers as usted has its translation corrected by code, with no model call
    Given the site's "es-419" writing guidelines choose the register "usted"
    And the English Story's second paragraph says "Read [the source](https://example.test/source): OpenAI says the AI system improved."
    And the translator writes "[Lee la fuente]⟦1⟧: OpenAI dice que el sistema de AI mejoró." for the second paragraph
    When the translation run for "es-419" runs
    Then the saved translation says "[Lea la fuente](https://example.test/source)"
    And the saved translation says "el sistema de IA mejoró"
    And the saved translation says "OpenAI dice"
    And the repairer was never asked
    And the run is saved, not held

  Scenario: A site that addresses readers as tu keeps its imperative, and the initialism is still corrected
    Given the English Story's second paragraph says "Read [the source](https://example.test/source): OpenAI says the AI system improved."
    And the translator writes "[Lee la fuente]⟦1⟧: OpenAI dice que el sistema de AI mejoró." for the second paragraph
    When the translation run for "es-419" runs
    Then the saved translation says "[Lee la fuente](https://example.test/source)"
    And the saved translation says "el sistema de IA mejoró"
    And the saved translation says "OpenAI dice"
    And the repairer was never asked

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

  Scenario: A paragraph the translator invents inside a note is repaired by the rewrite
    A note container is one block, and its own check can miss an extra paragraph inside it (the held Spanish "can-a-system-keep-a-secret"); the check of the whole body does not, and the run gives that finding back to
    the block it is in, with the instruction to delete any paragraph the English does not have.
    Given the English Story has a note "Out of office." between its paragraphs
    And the block check does not see the structure inside a note, so only the check of the whole body does
    And the translator adds the paragraph "Un párrafo inventado." inside the note
    And the repairer deletes any paragraph that is not in the English
    When the translation run for "es-419" runs
    Then the repairer was asked about the note only, with the invented paragraph named as a problem
    And the saved translation has the note without the invented paragraph
    And the run is saved, not held

  Scenario: A translator that keeps inventing the paragraph is held
    Given the English Story has a note "Out of office." between its paragraphs
    And the block check does not see the structure inside a note, so only the check of the whole body does
    And the translator adds the paragraph "Un párrafo inventado." inside the note
    And the repairer keeps the wrong wording
    When the translation run for "es-419" runs
    Then the run is held
    And the held reason names the structure difference

  Scenario: A paragraph the block check does see is repaired as before
    Given the English Story has a note "Out of office." between its paragraphs
    And the translator adds the paragraph "Un párrafo inventado." inside the note
    And the repairer deletes any paragraph that is not in the English
    When the translation run for "es-419" runs
    Then the saved translation has the note without the invented paragraph
    And the run is saved, not held

  Scenario: A note the translator keeps as written is not sent to the repairer
    Given the English Story has a note "Out of office." between its paragraphs
    When the translation run for "es-419" runs
    Then the repairer was never asked
    And the run is saved, not held

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

  Scenario: A Story republished while a run works is not overwritten by the older run
    Given the English Story is republished as version 4 while the version 3 run is translating
    When the translation run for "es-419" runs
    Then the run stops saying a newer source is requested
    And no translation is saved
    And the request "story-waymo#es-419" still names source version 4 and is wanted

  Scenario: A dry run prints the plan and writes nothing
    Given nobody asked for a translation
    When an editor previews the "es-419" translation of "story-waymo"
    Then the plan lists 5 blocks to translate and the glossary terms the translator will meet
    And no request was written

  Scenario: The cost prediction reads the runs of the procedure the named automation runs
    Given a site registered the translation procedure under its own key and an automation that runs it
    When a translation is planned or run for that automation
    Then the predicted cost comes from that procedure's measured runs, found through the automation's procedure key
    And a plan with no automation named predicts from no history
    And an automation that does not exist is refused naming it

  Scenario: A person starts one translation from the command line, with no automation
    Given a site that registered the translation procedure under SITE.story-localize and has the language enabled
    When an operator signed in with AWS credentials runs "papyrus stories localize" for a published Story and the language, naming no automation
    Then the translation request is written first
    And the procedure runner's own code loads the registered procedure, records a ProcedureRun with its usage, cost and output, and runs it in a child process signed as the operator
    And the command waits and prints the run id, status, cost and the procedure's output
    And no Automation, monitor or router publication is needed
    And a failed run exits non-zero and the same command continues from the finished stages

  Scenario: A run started from the command line refuses what it cannot do before it writes anything
    When "papyrus stories localize" is run without an automation on the signed-in lane
    Then it refuses, naming the operator lane
    And when no model key is in the process and no key parameter is named it refuses, naming both ways to give one
    And a procedure that is not registered is reported with the register command for its key
