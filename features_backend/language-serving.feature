Feature: Each language of a Story is served at its own address, and each page names the others
  Machines on Machines writes in English and serves translations of its Stories. English stays at the root, exactly where every page has
  always been; each other language lives under its own prefix (Spanish at /es/, Simplified Chinese at /zh/), with its own slug. A reader
  and a search engine find each language at a stable address, every page says which other languages it exists in, and a page that has no
  translation is never pretended into one.

  Background:
    Given a site that writes in English, Latin American Spanish and Simplified Chinese, with English at the root
    And Spanish is served under "es" and Chinese under "zh", and both are public with complete interface strings
    And the English article "the-sound" titled "The sound that can give away where you live" is published

  Scenario: English keeps its address and a Spanish translation lives under /es/ with its own slug
    When its Spanish translation "el-sonido" is published
    Then the English page is still at "articles/the-sound/index.html"
    And the Spanish page is at "es/articles/el-sonido/index.html" and declares lang "es-419"
    And no page of the site is under "/en/"

  Scenario: Every page lists hreflang for each published language and x-default, and is canonical to itself
    When its Spanish translation "el-sonido" is published
    Then the English page lists hreflang "en" and "es-419" and x-default pointing at the English page
    And the Spanish page lists the same hreflang links
    And neither page lists Chinese
    And each page is canonical to its own address
    And the Spanish page says og:locale "es_419" and its JSON-LD inLanguage is "es-419"
    And the Spanish page's alternates name each language in itself: "English" and "Español"

  Scenario: Publishing a translation renders its siblings again, and only them
    When its Spanish translation "el-sonido" is published
    Then the projection of the Spanish translation also wrote the English page
    And it wrote no other article page

  Scenario: Taking a translation down takes it out of the other pages
    Given its Spanish translation "el-sonido" is published
    When the Spanish translation is unpublished
    Then the Spanish page is gone
    And the English page lists no hreflang links

  Scenario: Each language's listings list only that language's Stories
    Given the English article "the-other" titled "Another story" is published
    When its Spanish translation "el-sonido" is published
    Then the English home and the English articles listing link "the-sound" and "the-other" and no Spanish page
    And the Spanish home and the Spanish articles listing link only "el-sonido"
    And the English home and the Spanish home name each other in hreflang

  Scenario: The sitemap index lists one sitemap per language
    When its Spanish translation "el-sonido" is published
    Then the sitemap index lists "sitemap-0.xml" and "es/sitemap-0.xml"
    And the Spanish sitemap lists the Spanish page and no English one

  Scenario: A language that is not public gets no page and is in no list
    Given Spanish is enabled but not public
    When its Spanish translation "el-sonido" is published
    Then there is no page under "es/"
    And the English page lists no hreflang links

  Scenario: A public language with incomplete interface strings is refused, naming what is missing
    Given the Spanish interface strings lack "section.articles.label"
    When the multilingual site is projected
    Then the projection is refused naming "es-419: section.articles.label"

  Scenario: A Chinese translation is served under a Chinese-character slug, encoded the same way everywhere
    When its Chinese translation with the slug "能泄露你住在哪里的声音" is published
    Then the Chinese page's object key is "zh/articles/能泄露你住在哪里的声音/index.html" in Unicode NFC
    And its canonical address, its hreflang links and its sitemap entry are the percent-encoded form of that key
    And the Chinese home links the page by the same percent-encoded address
    And the edge invalidation paths of the page are percent-encoded, one path per form, each counted once

  Scenario: A slug written in decomposed Unicode is stored and served in composed form
    When its Chinese translation is published with the slug "가" written in decomposed jamo
    Then the Chinese page's object key holds the composed "가" and no decomposed character

  Scenario: Renaming a Chinese translation redirects its old address, in the encoded form a browser requests
    Given its Chinese translation with the slug "能泄露你住在哪里的声音" is published
    When the Chinese translation is renamed to "你住在哪里"
    Then the redirect store sends the encoded old address to the encoded new address
    And the English page's hreflang names the new Chinese address

  Scenario: A site page knows where each link goes in its own language
    Given the English article "the-other" titled "Another story" is published
    When its Spanish translation "el-sonido" is published
    Then from the Spanish page a link to "/articles/the-sound/" goes to "/es/articles/el-sonido/" and stays in Spanish
    And from the Spanish page a link to "/articles/the-other/" stays where it is and is marked as leaving Spanish

  Scenario: A translated Concept page is served under /concepts/ in its language, and the English one keeps /wiki/
    Given the English Concept page "abliteration" is published in the wiki
    When its Spanish translation "abliteracion" of the Concept page is published
    Then the English Concept page stays at "wiki/abliteration/index.html" and the Spanish one is at "es/concepts/abliteracion/index.html"
