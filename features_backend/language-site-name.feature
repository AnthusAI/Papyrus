Feature: A language edition has the publication's name in its own language
  A publication's name is part of its words. A public language gives it as the interface string `site.name` (and `site.shortName`, `site.publisher` and
  `feeds.title` when the site sets those), and the edition uses it everywhere the name appears: the title suffix and the home's title, `og:site_name`,
  the structured data's publisher, the feeds' titles and the masthead. The structured data of every page lists the name in the other languages as
  `alternateName` (the primary language's first), and the home carries a WebSite block, so a search engine joins the editions as one publication.

  Background:
    Given a site that writes in English, Latin American Spanish and Simplified Chinese, with English at the root
    And Spanish is served under "es" and Chinese under "zh", and both are public with complete interface strings
    And the English article "the-sound" titled "The sound that can give away where you live" is published

  Scenario: Each edition says the name in its own language everywhere and lists the others as alternate names
    When its Spanish translation "el-sonido" and its Chinese translation "声音" are published
    Then the Spanish home says its name "Máquinas Sobre Máquinas" in its title, og:site_name, structured data and feed
    And the Chinese home says its name "机器论机器" in its title, og:site_name, structured data and feed
    And the English home says its name "Machines on Machines" in its title, og:site_name, structured data and feed
    And the Spanish home lists "Machines on Machines" and "机器论机器" as alternate names
    And the English home lists "Máquinas Sobre Máquinas" and "机器论机器" as alternate names
    And the Spanish article says its publisher "Máquinas Sobre Máquinas" with alternate names "Machines on Machines" and "机器论机器"

  Scenario: A public language without the name is refused
    Given the Spanish interface strings lack "site.name"
    When the multilingual site is projected
    Then the projection is refused naming "es-419: site.name"
