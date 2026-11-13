Feature: A publication decides how its terms are translated
  A publication keeps a glossary and do-not-translate list per language (PPY-795b4b). It is guideline data, the kind `glossary`: the
  publication's document holds what every language shares (terms kept exactly as written), and each language overlay holds that
  language's approved forms, including the target locale's naming conventions (Paris is París in Latin American Spanish). A section may
  add its own. Laying over is by term: a later layer's entry for a term replaces the earlier one unless the publication locks the entries.

  The glossary has two readers, and both take its entries from the same place: the translator is told only the entries whose term occurs in
  the blocks it translates, and the faithfulness check verifies each one (a missing approved form is a faithfulness finding). Names of
  people, organisations and products need no entry: they stay as written unless the glossary gives an approved local form. Nothing here
  learns a term by itself; starter documents for a language are data an admin saves.

  Scenario: The translator is told only the terms it will meet
    Given a glossary of forty entries for "es-419"
    And a block that contains two of the source terms
    When the entries for the block are chosen
    Then exactly those two entries are chosen

  Scenario: A locale's approved form of a name is used
    Given the Latin American Spanish starter glossary
    When a block saying "The Justice Department sued in North Carolina." is translated as "El Justice Department demandó en North Carolina."
    Then the faithfulness check reports that "Justice Department" should be "Departamento de Justicia"
    And it reports that "North Carolina" should be "Carolina del Norte"

  Scenario: The approved form passes the check
    Given the Latin American Spanish starter glossary
    When a block saying "The Justice Department sued in North Carolina." is translated as "El Departamento de Justicia demandó en Carolina del Norte."
    Then the faithfulness check reports no glossary finding

  Scenario: A do-not-translate term must stay as written
    Given the Simplified Chinese starter glossary
    When a block saying "The edits are often called abliteration." is translated as "这类改动通常称为消融。"
    Then the faithfulness check reports that "abliteration" must stay unchanged

  Scenario: Names default to do-not-translate
    Given the Simplified Chinese starter glossary
    When a block saying "Researchers at Hugging Face disagreed." is translated as "抱抱脸的研究人员意见不一。"
    Then the faithfulness check reports that the name "Hugging Face" is missing

  Scenario: An entry needs either approved forms or do-not-translate
    When an admin saves a glossary entry for "computer" with neither translations nor doNotTranslate
    Then the document is refused, saying the entry needs either translations or doNotTranslate

  Scenario: A language overlay replaces the publication's entry for the same term
    Given the publication's glossary keeps "Congress" unchanged
    And the "es-419" glossary renders "Congress" as "Congreso"
    When the glossary is resolved for "es-419"
    Then "Congress" is rendered as "Congreso"
    And the glossary's version changes when any entry changes

  Scenario: The starter glossaries carry the experiment's name findings
    Then the "es-419" starter glossary renders "AI" as "IA", "Paris" as "París", "Congress" as "Congreso", "Justice Department" as "Departamento de Justicia" and "North Carolina" as "Carolina del Norte"
    And the "zh-Hans" starter glossary renders "Paris" as "巴黎" and keeps "AI" and "abliteration" unchanged
