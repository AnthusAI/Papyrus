Feature: Each language serves its sections, types and pages under path segments in its own language
  A Spanish reader sees /es/articulos/ and a Chinese reader /zh/文章/, not English words inside the address. The segments are a table in the site's
  language settings (languages.segments), one table per language, editable without code. English keeps every address it has; the old English
  segments under /es/ and /zh/ were published and indexed, so each of their pages redirects permanently to the translated one, keeping the path.

  Background:
    Given a site that writes in English, Latin American Spanish and Simplified Chinese, with English at the root
    And Spanish is served under "es" and Chinese under "zh", and both are public with complete interface strings
    And the language segments are "es-419": articles is "articulos", concepts is "conceptos"; "zh-Hans": articles is "文章", concepts is "概念"
    And the English article "the-sound" titled "The sound that can give away where you live" is published

  Scenario: A translated Story and its listings live under the translated segment
    When its Spanish translation "el-sonido" is published
    And its Chinese translation with the slug "能泄露你住在哪里的声音" is published
    Then the English page is still at "articles/the-sound/index.html"
    And the Spanish page is at "es/articulos/el-sonido/index.html" and declares lang "es-419"
    And the page "es/articulos/index.html" exists and "es/articles/index.html" does not
    And the page "zh/文章/能泄露你住在哪里的声音/index.html" exists and "zh/articles/index.html" does not
    And the Spanish Concepts listing is "es/conceptos/index.html" and the Chinese one "zh/概念/index.html"

  Scenario: Canonical, hreflang, sitemap, listings and the switcher use the translated addresses, percent-encoded for Chinese
    When its Spanish translation "el-sonido" is published
    And its Chinese translation with the slug "能泄露你住在哪里的声音" is published
    Then the English page names "/es/articulos/el-sonido/" and the percent-encoded "/zh/文章/能泄露你住在哪里的声音/" in hreflang
    And the Chinese page is canonical to the percent-encoded "/zh/文章/能泄露你住在哪里的声音/" and lists no raw Chinese character in any address
    And the Spanish sitemap lists "/es/articulos/el-sonido/" and the Spanish listing "/es/articulos/"
    And the Spanish home links "/es/articulos/el-sonido/" and no "/es/articles/"
    And the Articles listing is offered in each language at "/articles/", "/es/articulos/" and the percent-encoded "/zh/文章/"
    And the Concepts listing is offered in each language at "/wiki/", "/es/conceptos/" and the percent-encoded "/zh/概念/"

  Scenario: Every old English-segment address under a language prefix redirects to its translated address
    When its Spanish translation "el-sonido" is published
    And its Chinese translation with the slug "能泄露你住在哪里的声音" is published
    And the multilingual site is projected
    Then the redirect store sends "/es/articles/" to "/es/articulos/" and "/es/articles/el-sonido/" to "/es/articulos/el-sonido/"
    And it sends "/es/concepts/" to "/es/conceptos/"
    And it sends the percent-encoded "/zh/articles/能泄露你住在哪里的声音/" to the percent-encoded "/zh/文章/能泄露你住在哪里的声音/"
    And it sends "/zh/articles/" to the percent-encoded "/zh/文章/"
    And no English address is redirected and every redirect source and target is ASCII

  Scenario: A table that would serve two paths at one address is refused
    Given the language segments are "es-419": concepts is "articles"
    When the multilingual site is projected
    Then the projection is refused naming "would both be served at /articles/"
