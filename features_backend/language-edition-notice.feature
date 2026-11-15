Feature: A language edition says the publication's notice in its own language
  A satire publication says so on every page, Markdown twin, feed entry and structured-data block (Humorus rule 7). When it also serves a
  second language, the Spanish reader of the Spanish edition, the Spanish Markdown twin, the Spanish feed and the structured data of the
  Spanish page get the notice in Spanish, from the language's interface strings. A language whose strings lack the notice is not public: the
  Spanish edition never says it in English by falling back.

  Background:
    Given a site that writes in English, Latin American Spanish and Simplified Chinese, with English at the root
    And Spanish is served under "es" and Chinese under "zh", and both are public with complete interface strings
    And the site's notice is "Satire" and "Everything on this site is invented." and Spanish says "Sátira" and "Todo lo que hay en este sitio es inventado."
    And the English article "the-sound" titled "The sound that can give away where you live" is published

  Scenario: The Spanish edition says the notice in Spanish on its pages, its Markdown twin, its feeds and its structured data
    When its Spanish translation "el-sonido" is published
    Then the Spanish page, its Markdown twin, the Spanish feeds and the Spanish page's structured data say the notice in Spanish and not in English
    And the English page, its Markdown twin and the English feed still say it in English

  Scenario: A public language whose strings lack the notice is refused
    Given the Spanish interface strings lack "notice.text"
    When the multilingual site is projected
    Then the projection is refused naming "es-419: notice.text"
