Feature: A translated page says who wrote the translation: an AI, or the person who wrote the copy
  A localization version records its kind in `metadata.localization.translation`: `machine` for a translation the procedure wrote
  (`papyrus stories localize`) and `imported` for finished copy a person or another agent wrote (`papyrus stories import-translation`, PPY-b64b0b), whose
  provenance names the writer. The page of the translation, its Markdown twin and its structured data read that kind (PPY-5faf82).

  A machine translation says in its own language that an AI translated it from the original, with a link to the original; its twin says
  `Translation: machine`, and its structured data names no translator. An imported translation says in its own language that the copy was written by
  the named writer, with the same link, and never says AI; its twin says `Translation: imported` and `Written by`, and its structured data has a
  `translator`. Both say they are a `translationOfWork` of the original. The words are interface strings of the language: `translation.label` for a
  machine translation and `translation.importedLabel`, with `{author}` and `{original}`, for an imported one. A language that serves an imported
  translation without the second key is refused when the page is drawn, never shown with the machine line. Everything here is synthetic: nothing
  reaches a network and no model runs.

  Background:
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And the English Story is served by a site that publishes Spanish under "es"

  Scenario: A machine translation still says an AI translated it
    Given a scripted translator, judge and repairer for "es-419"
    And an editor asked for the "es-419" translation of "story-waymo"
    And the translation run for "es-419" has finished
    When a person publishes the "es-419" translation
    Then the Spanish page says "Traducido por IA del original en inglés" and links the English page
    And the Spanish page does not say who wrote the copy
    And the Spanish Markdown twin says language "es-419", translation "machine" and the English page it was translated from
    And the Spanish Markdown twin names no writer
    And the Spanish page's JSON-LD names no translator

  Scenario: An imported Spanish translation says who wrote it, in Spanish, and never says AI
    Given finished Spanish copy for "story-waymo" written for the "es-419" edition
    And the copy has the two paragraphs the site shows and no picture
    And "Ana Writer" imported the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    When a person publishes the "es-419" translation
    Then the Spanish page says "Escrito por Ana Writer, a partir del" and links the English page to its "original en inglés"
    And the Spanish page does not say an AI translated it
    And the Spanish Markdown twin says language "es-419", translation "imported" and the English page it was translated from
    And the Spanish Markdown twin says it was written by "Ana Writer"
    And the Spanish page's JSON-LD names "Ana Writer" as translator and is a translationOfWork of the English page in "en"

  Scenario: An imported Chinese translation says who wrote it, in Chinese
    Given finished Chinese copy for "story-waymo" written for the "zh-Hans" edition
    And the copy has the two paragraphs the site shows and no picture
    And "Wei Writer" imported the copy as the "zh-Hans" translation of "story-waymo" because "Beijing draft"
    When a person publishes the "zh-Hans" translation
    Then the Chinese page says "由 Wei Writer 撰写，对应" and links the English page to its "英文原文"
    And the Chinese page does not say an AI translated it
    And the Chinese Markdown twin says it was written by "Wei Writer"

  Scenario: The writer's name is text and is escaped
    Given finished Spanish copy for "story-waymo" written for the "es-419" edition
    And the copy has the two paragraphs the site shows and no picture
    And "Ana <b>Writer</b> & Co" imported the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    When a person publishes the "es-419" translation
    Then the Spanish page says "Escrito por Ana &lt;b&gt;Writer&lt;/b&gt; &amp; Co, a partir del" and links the English page to its "original en inglés"

  Scenario: A language that serves an imported translation needs the words of its line
    Given finished Spanish copy for "story-waymo" written for the "es-419" edition
    And the copy has the two paragraphs the site shows and no picture
    And the Spanish interface strings lack "translation.importedLabel"
    And "Ana Writer" imported the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    When a person publishes the "es-419" translation
    Then drawing the Spanish page is refused naming "translation.importedLabel"

  Scenario: An imported line with no place for the writer's name is refused
    Given finished Spanish copy for "story-waymo" written for the "es-419" edition
    And the copy has the two paragraphs the site shows and no picture
    And the Spanish imported-translation line is "Escrito a partir del {original}"
    And "Ana Writer" imported the copy as the "es-419" translation of "story-waymo" because "Beijing draft"
    When a person publishes the "es-419" translation
    Then drawing the Spanish page is refused naming "{author}"
