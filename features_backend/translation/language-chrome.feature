Feature: The words and dates the standard front end prints are the page's language's
  A Spanish page is Spanish all the way down. The skip link says what the language's interface strings say, and the dates on its cards, bylines and
  article headers are written in the language's own date format, so a Spanish reader never sees "Skip to main content" or "2026-11-01" on a
  page in their language.

  Background:
    Given a site that writes in English, Latin American Spanish and Simplified Chinese, with English at the root
    And Spanish is served under "es" and Chinese under "zh", and both are public with complete interface strings
    And the English article "the-sound" titled "The sound that can give away where you live" is published

  Scenario: The skip link uses the language's string on every page of the language
    When its Spanish translation "el-sonido" is published
    And its Chinese translation with the slug "声音" is published
    Then the English "index.html" page's skip link says "Skip to main content"
    And the Spanish "es/index.html" page's skip link says "Saltar al contenido principal"
    And the Spanish "es/articles/el-sonido/index.html" page's skip link says "Saltar al contenido principal"
    And the Chinese "zh/index.html" page's skip link says "跳到主要内容"

  Scenario: A public language whose strings lack the skip link is refused
    Given the Spanish interface strings lack "skipToMain"
    When the multilingual site is projected
    Then the projection is refused naming "es-419: skipToMain"

  Scenario: The primary language needs the skip link's words too
    Given the English interface strings lack "skipToMain"
    When the multilingual site is projected
    Then the projection is refused naming "en: skipToMain"

  Scenario: Dates on a language's pages are in that language's date format
    When its Spanish translation "el-sonido" is published
    And its Chinese translation with the slug "声音" is published
    Then the Spanish "es/index.html" page dates its card "1 de noviembre de 2026"
    And the Spanish "es/articles/el-sonido/index.html" page dates its byline "1 de noviembre de 2026"
    And the Chinese "zh/index.html" page dates its card "2026年11月1日"
    And the English "index.html" page dates its card "2026-11-01"
    And no page of the Spanish edition shows a date as "2026-11-01"

  Scenario: A site's own date format still rules its primary language, and the editions keep their own language's format
    Given the site writes dates as "%d %B %Y"
    When its Spanish translation "el-sonido" is published
    Then the English "index.html" page dates its card "01 November 2026"
    And the Spanish "es/index.html" page dates its card "1 de noviembre de 2026"
