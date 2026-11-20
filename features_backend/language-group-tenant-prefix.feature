@backend @languages @checklist-gate
Feature: On a tenant backend, every reader of a language group strips the tenant prefix before it decides what is a translation
  A tenant backend stores each language group with the tenant in front of it: the Story `story-rivers` of the tenant `machines-on-machines` is in the group
  `machines-on-machines#story-rivers`. A Story is a translation when its group, without the prefix, is another lineage than its own. A reader that forgot the
  tenant saw the prefixed group as a different lineage and so treated every original as a translation of `machines-on-machines#<itself>`: tagging an
  original with a concept failed, and the roundup and the announce agent took a prefixed translation for a Story of its own. The tenant is a required argument of
  `translation_original` and `localization_original`, so a caller cannot leave it out, and each caller passes its client's tenant.
  (`papyrus stories link-concept` itself is covered in concept-tags.feature.) Nothing here reaches a real site, login or AWS.

  Background:
    Given the tenant backend "machines-on-machines" has the published Story "story-rivers" and its Spanish translation "story-rivers--es-419", each stored with a prefixed language group

  Scenario: The original is not a translation and the translation names its original
    Then the original "story-rivers" is not a translation of anything
    And the translation "story-rivers--es-419" is a translation of "story-rivers"

  Scenario: The newsletter roundup takes the original and leaves out the translation
    When the roundup lists the Stories it may include
    Then the roundup lists "story-rivers" and not "story-rivers--es-419"

  Scenario: The announce agent reads the original as a Story and the translation as a translation
    When the announce agent reads the Story "story-rivers" and the Story "story-rivers--es-419"
    Then the original is not marked as a translation
    And the translation is marked as a translation

  Scenario: A translation is gated by its own language checklist and the original by the Story checklist
    Then publishing "story-rivers--es-419" is checked against its own language checklist
    And publishing "story-rivers" is checked against the Story checklist
