Feature: Finished copy written by a person or another agent is attached as a Story's translation
  A published English Story is translated by a model (`papyrus stories localize`), and a person corrects a published translation
  (`papyrus stories correct-translation`). Neither takes copy that was written separately and is already finished. The command
  `papyrus stories import-translation` does (PPY-b64b0b): it saves the copy as the next version of the sibling lineage `<story>--<language>`, the way the
  translation procedure saves one, as an unpublished companion edition of the English version it pairs with. The version's author is the writer, and its
  provenance says the copy was written and not machine-generated. Every block is the writer's, owner human and pinned, so a later translation run keeps the
  copy exactly. The version's front matter says who made it for the site's standard byline ("By various bots", "By various bots and NAME", or "By NAME"):
  `author` is the writer and `drafting: {by: AI}` is there only when the caller says bots helped (`--drafting-by-ai`), never inherited from the English
  Story, whose byline is the English's. No model is called: the parity and glossary rules and the language's copy-edit policies check each block and the whole body, and an
  error-severity finding holds the version with a flag review request, exactly as it holds a machine translation. The copy must line up with the English
  block for block, and it must not change a link, a credit or a figure; a copy that does not, or that asks for a language the site does not write in, an
  unpublished Story or a translation, is refused and nothing is saved. The Story's translation request is written finished so that
  `papyrus stories localize --all` counts the language up to date and leaves the copy alone. Importing never publishes.

  Background:
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And finished Spanish copy for "story-waymo" written for the "es-419" edition

  Scenario: Finished copy becomes an unpublished companion edition of the English version it pairs with
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft, reviewed by the Madrid editors"
    Then the import is saved, not held
    And a version of "story-waymo--es-419" exists written in "es-419" in the language group "story-waymo"
    And that version is by "Ana Writer", unpublished, has no board stage and its change reason names the writer and the reason
    And it names source version 3 and the source's content hash
    And its title, dek and body are the copy's
    And its address was drafted by the language's slug policy
    And the imported copy is not published

  Scenario: The provenance says the copy was written, not machine-generated, and no model was called
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the version says it is an imported translation written by "Ana Writer", imported by "agent-session"
    And its provenance says the copy was written by "Ana Writer" and was not machine-generated
    And its provenance names no model and no cost, and no judge was given to the checks

  Scenario: The writer is the byline's author, and the English Story's byline is not inherited
    Given the English Story is drafted by AI and names the author "Ryan Porter"
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the saved version's front matter has the author "Ana Writer" and no drafting by AI

  Scenario: The caller says bots helped, so the byline gets the bots
    Given the English Story is drafted by AI and names the author "Ryan Porter"
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft" saying bots helped
    Then the saved version's front matter has the author "Ana Writer" and drafting by AI

  Scenario: An English Story with no front matter still gets the writer as the author
    Given the English Story has no front matter
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft" saying bots helped
    Then the saved version's front matter has the author "Ana Writer" and drafting by AI

  Scenario: Every block is the writer's and pinned
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then in its alignment all 5 blocks are human and pinned and name the English blocks they pair with

  Scenario: The original's stored picture is carried so the translation can be published
    Given the English Story has the stored picture "assets/waymo.png"
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the saved translation has the stored picture "assets/waymo.png", so it can be published

  Scenario: Chinese copy is attached the same way, with the language's own address
    Given finished Chinese copy for "story-waymo" written for the "zh-Hans" edition
    When "Wei Writer" imports the copy as the "zh-Hans" translation of "story-waymo" because "Beijing draft"
    Then the import is saved, not held
    And the saved copy is written in "zh-Hans" in the language group "story-waymo" and its address is made of the title's characters
    And in its alignment all 5 blocks are human and pinned and name the English blocks they pair with

  Scenario: A later translation run keeps the copy exactly
    Given a scripted translator, judge and repairer for "es-419"
    And "Ana Writer" imported the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    When the English Story's second paragraph says "The [report](https://example.test/report) covers 14 cities." in version 4 and the translation is run again
    Then the second paragraph of the newest translation still says "El [informe](https://example.test/report) abarca 12 ciudades."
    And the newest provenance marks that paragraph as a conflict
    And the newest translation is held saying the person's wording no longer matches the English

  Scenario: The Story's translation request is written finished, so translating the whole site leaves the copy alone
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the request for "es-419" is saved for source version 3 and names no automation
    And surveying the whole site for "es-419" finds the Story up to date

  Scenario: An error finding holds the copy exactly as it holds a machine translation
    Given the copy says "70 %" where it says "68 %"
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the import is held and the output names the number finding
    And the version is saved with the outcome held and a flag review request says why
    And the request for "es-419" is held for source version 3
    And surveying the whole site for "es-419" finds the Story up to date
    And the imported copy is not published

  Scenario: Findings that are not errors are printed as advice and do not hold the copy
    Given the copy says "Cabe destacar que los autos de Waymo pueden chocar un 68 % menos, según la empresa." where it says "Los autos de Waymo pueden chocar un 68 % menos, según la empresa."
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the import is saved, not held
    And the output prints a finding that is not an error

  Scenario: A dry run prints the alignment and the findings and writes nothing
    Given the copy says "70 %" where it says "68 %"
    When "Ana Writer" previews importing the copy as the "es-419" translation of "story-waymo"
    Then the preview shows the title, the dek and every body block paired with its English block
    And the preview names the number finding
    And no version of "story-waymo--es-419" is saved and no request is written

  Scenario: A copy with an extra paragraph cannot be aligned, and the refusal says where
    Given the copy has the extra paragraph "Un párrafo que el inglés no tiene." after its first paragraph
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the import is refused saying the English body has 3 blocks and the copy has 4
    And the refusal says they first stop matching at block 2
    And no version of "story-waymo--es-419" is saved and no request is written

  Scenario: A copy that joins two blocks is refused
    Given the copy joins its first two paragraphs
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the import is refused saying the English body has 3 blocks and the copy has 2
    And no version of "story-waymo--es-419" is saved and no request is written

  Scenario: A changed link target is refused
    Given the copy says "https://example.test/otro" where it says "https://example.test/report"
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the import is refused saying a link target, address, citation, credit or other fixed part is not the English's
    And no version of "story-waymo--es-419" is saved and no request is written

  Scenario: A translated credit is refused, while the figure's alt text may be written in the language
    Given the copy says "Imagen: Jane Doe, CC BY 2.0" where it says "Image: Jane Doe, CC BY 2.0"
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the import is refused saying a link target, address, citation, credit or other fixed part is not the English's
    And no version of "story-waymo--es-419" is saved and no request is written

  Scenario: A copy without the dek the English has is refused
    Given the copy's front matter has no dek
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the import is refused saying the front matter lacks a dek
    And no version of "story-waymo--es-419" is saved and no request is written

  Scenario: Front matter that is not the copy's own text is refused
    Given the copy's front matter also has "slug: bajan-los-choques"
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the import is refused saying the front matter has slug
    And no version of "story-waymo--es-419" is saved and no request is written

  Scenario: The front matter may open the body file
    Given the copy's front matter is the opening block of its body file
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the import is saved, not held

  Scenario: Importing the same copy again saves nothing new
    Given "Ana Writer" imported the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the import saved nothing new
    And the translation lineage "story-waymo--es-419" holds 1 version

  Scenario: Revised copy is the next version, and the earlier one stays in the history
    Given "Ana Writer" imported the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    And the copy says "cubre" where it says "abarca"
    When "Luis Reviser" imports the copy as the "es-419" translation of "story-waymo" because "Revised after the Madrid read"
    Then the translation lineage "story-waymo--es-419" holds 2 versions
    And the second version is by "Luis Reviser", has the first as its predecessor and the first is superseded
    And the output says it replaces version 1, an imported copy

  Scenario: A translation run in progress is not written over
    Given a translation run for "es-419" is in progress for "story-waymo"
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the import is refused saying a translation run is in progress
    And no version of "story-waymo--es-419" is saved

  Scenario: A language the site does not write in is refused
    Given the English Story is published as the site lists it
    And the site writes in "en" and "es-419"
    When "Ana Writer" imports the copy as the "zh-Hans" translation of "story-waymo" because "Beijing draft"
    Then the import is refused saying the site does not write in "zh-Hans"
    And no version of "story-waymo--zh-Hans" is saved and no request is written

  Scenario: A language that does not exist is refused
    Given the English Story is published as the site lists it
    And the site writes in "en" and "es-419"
    When "Ana Writer" imports the copy as the "fr" translation of "story-waymo" because "Beijing draft"
    Then the import is refused saying there is no language pack for "fr"

  Scenario: A Story that is not published is refused
    Given the English Story is not published
    And the site writes in "en" and "es-419"
    When "Ana Writer" imports the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    Then the import is refused saying the Story is not published and to publish the English Story first

  Scenario: A Story that is itself a translation is refused
    Given "story-waymo--es-419" is a published translation of "story-waymo"
    And the site writes in "en", "es-419" and "zh-Hans"
    When "Ana Writer" imports the copy as the "zh-Hans" translation of "story-waymo--es-419" because "Beijing draft"
    Then the import is refused saying the Story is itself a translation

  Scenario: The command refuses a missing writer and reads the files
    When "Ana Writer" runs the command without --written-by
    Then the command is refused saying --written-by is required
    When "Ana Writer" runs the command with a body file that does not exist
    Then the command is refused saying the body file is not a file
