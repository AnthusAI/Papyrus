Feature: A translated page says what it is, and never claims AI for copy a person wrote
  A localization version records its kind in `metadata.localization.translation`: `machine` for a translation the procedure wrote
  (`papyrus stories localize`) and `imported` for finished copy a person or another agent wrote (`papyrus stories import-translation`, PPY-b64b0b). The kind is
  record data; what the page says about it is small. Who made a Story is the byline's to say ("By various bots", "By various bots and NAME" or "By NAME",
  from the version's `author` and `drafting` front matter, translated into the page's language), so an imported translation's page adds nothing about its
  writer (PPY-376575).

  A machine translation says in its own language that an AI translated it from the original, with a link to the original; its twin says
  `Translation: machine`. An imported translation shows only the link to the original, in the words of `translation.original`, and never says AI; its twin
  gives the language and where it was translated from and names no kind and no writer; its structured data has no `translator`. Both are a
  `translationOfWork` of the original. The imported line needs no interface string of its own: a language that serves one has `translation.original` already.
  Everything here is synthetic: nothing reaches a network and no model runs.

  Background:
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And the English Story is served by a site that publishes Spanish under "es"

  Scenario: A machine translation still says an AI translated it
    Given a scripted translator, judge and repairer for "es-419"
    And an editor asked for the "es-419" translation of "story-waymo"
    And the translation run for "es-419" has finished
    When a person publishes the "es-419" translation
    Then the Spanish page says "Traducido por IA del" and links the English page to its "original en inglés"
    And the Spanish Markdown twin says language "es-419", translation "machine" and the English page it was translated from
    And the Spanish page's JSON-LD names no translator

  Scenario: An imported Spanish translation shows only the link to the original and never says AI
    Given finished Spanish copy for "story-waymo" written for the "es-419" edition
    And the copy has the two paragraphs the site shows and no picture
    And "Ana Writer" imported the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    When a person publishes the "es-419" translation
    Then the Spanish page's translation line is only the link to the English page, "original en inglés"
    And the Spanish page does not say an AI translated it or who wrote it
    And the Spanish Markdown twin says language "es-419" and the English page it was translated from, and names no translation kind and no writer
    And the Spanish page's JSON-LD names no translator and is a translationOfWork of the English page in "en"

  Scenario: An imported Chinese translation shows only the link to the original
    Given finished Chinese copy for "story-waymo" written for the "zh-Hans" edition
    And the copy has the two paragraphs the site shows and no picture
    And "Wei Writer" imported the copy as the "zh-Hans" translation of "story-waymo" because "Beijing draft"
    When a person publishes the "zh-Hans" translation
    Then the Chinese page's translation line is only the link to the English page, "英文原文"
    And the Chinese page does not say an AI translated it
