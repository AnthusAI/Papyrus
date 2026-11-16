Feature: A person's correction of a published translation is saved as their own wording
  A translation is a Story lineage of its own (`<story>--<language>`), written by the translation procedure. When a person finds a flaw in it, the
  command `papyrus stories correct-translation` saves their edit as a new version of that lineage (PPY-ef71cd, PPY-c0aebc). Each block the edit changes
  becomes the person's in the version's alignment: owner `human`, pinned. A later translation run keeps a pinned block exactly as written; if its
  English source changed, the block is reported as a conflict and nothing is overwritten. The provenance of the new version says honestly who edited,
  who applied the edit, why, and what each changed block said before and after. Whoever approved the edit is recorded there as metadata and never
  appears in the page's text, a credit or a caption. A correction changes wording only: it never touches a link target, a credit or another part of a
  block that a translator never sees, and an edit that matches nothing, or matches more places than it names, saves nothing.

  Background:
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And a scripted translator, judge and repairer for "es-419"
    And an editor asked for the "es-419" translation of "story-waymo"
    And the translation run for "es-419" has finished

  Scenario: An edit is saved as a new version whose changed block is the person's
    When a person named "Pat Editor" corrects "abarca" to "cubre" in the "es-419" translation because "the verb reads better", approved by "Sam Approver"
    Then a new version of "story-waymo--es-419" exists whose second paragraph says "El [informe](https://example.test/report) cubre 12 ciudades."
    And that version is by "Pat Editor", unpublished and has the earlier version as its predecessor
    And in its alignment only the second paragraph is human and pinned
    And its provenance records the editor "Pat Editor", the applier "agent-session", the reason, and the paragraph before and after
    And the approver "Sam Approver" is in the provenance and nowhere in the page's text, title, dek or change reason
    And the English Story's version is unchanged

  Scenario: A later translation keeps the person's wording
    Given a person named "Pat Editor" corrected "abarca" to "cubre" in the "es-419" translation because "the verb reads better"
    When the English Story is republished as version 4 with one paragraph changed and the translation asked for again
    And the translation run for "es-419" runs
    Then the second paragraph of the newest translation still says "El [informe](https://example.test/report) cubre 12 ciudades."

  Scenario: The person's wording survives a change of its own English source as a conflict
    Given a person named "Pat Editor" corrected "abarca" to "cubre" in the "es-419" translation because "the verb reads better"
    When the English Story's second paragraph says "The [report](https://example.test/report) covers 14 cities." in version 4 and the translation is run again
    Then the second paragraph of the newest translation still says "El [informe](https://example.test/report) cubre 12 ciudades."
    And the newest provenance marks that paragraph as a conflict

  Scenario: Wording that occurs more than once is refused unless every occurrence is named
    When a person corrects "Waymo" to "Waymo Inc." in the "es-419" translation without saying every
    Then the correction is refused saying "Waymo" occurs more than once
    And no new version of "story-waymo--es-419" is saved

  Scenario: Every occurrence may be named
    When a person named "Pat Editor" corrects every "Waymo" to "WAYMO" in the "es-419" translation because "the company writes its name in capitals"
    Then the title and the first paragraph of the newest translation say "WAYMO"

  Scenario: An edit that would change a link target is refused
    When a person corrects "https://example.test/report" to "https://example.test/other" in the "es-419" translation without saying every
    Then the correction is refused saying it would change a fixed part
    And no new version of "story-waymo--es-419" is saved

  Scenario: Wording that is not in the translation is refused
    When a person corrects "no existe" to "existe" in the "es-419" translation without saying every
    Then the correction is refused saying "no existe" is not in the translation
    And no new version of "story-waymo--es-419" is saved

  Scenario: A dry run shows the blocks before and after and writes nothing
    When a person previews correcting "abarca" to "cubre" in the "es-419" translation
    Then the preview shows the second paragraph before and after
    And no new version of "story-waymo--es-419" is saved

  Scenario: The command publishes the new version only when asked, and verification needs publishing
    When a person runs the command correcting "abarca" to "cubre" with "--publish --verify"
    Then the ordinary publish of the new version is run with verification
    When a person runs the command correcting "abarca" to "cubre" with "--verify"
    Then the command is refused because verification goes with publishing
