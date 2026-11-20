Feature: Core draws a language switcher on every page that exists in more than one language
  A site that serves more than one public language gets a language switcher from the standard front end, with no site code: it draws the page's
  alternates, each language in its own name, and marks the language the reader is in. It is on by default and the site chooses only where it
  sits and how loud it is, as it does for the publication's notice. Every reader can use it with a keyboard and a screen reader, and nothing in
  it relies on colour alone, on a border, or on an icon with no words.

  Background:
    Given a site that writes in English, Latin American Spanish and Simplified Chinese, with English at the root
    And Spanish is served under "es" and Chinese under "zh", and both are public with complete interface strings
    And the English article "the-sound" titled "The sound that can give away where you live" is published

  Scenario: A page that exists in two languages offers both, each in its own name, and marks the current one
    When its Spanish translation "el-sonido" is published
    Then the English "articles/the-sound/index.html" page has a language switcher labelled "Language: English" listing "English" and "Español"
    And the English page's switcher marks "English" as the current language with a check mark and aria-current
    And the Spanish "es/articles/el-sonido/index.html" page has a language switcher labelled "Idioma: Español" listing "English" and "Español"
    And the Spanish page's switcher links to the English page at "/articles/the-sound/" and each option carries its language and hreflang

  Scenario: Each language of the switcher goes to the same page in that language
    When its Spanish translation "el-sonido" is published
    And its Chinese translation with the slug "声音" is published
    Then the English "articles/the-sound/index.html" page's switcher links to "/articles/the-sound/", "/es/articles/el-sonido/" and "/zh/articles/%E5%A3%B0%E9%9F%B3/"

  Scenario: The switcher offers a listing the language has no Story in yet
    Then the English "articles/index.html" page's switcher offers "English" and "Español" and "中文"
    And the Spanish "es/articles/index.html" page is not indexed
    And the English "articles/index.html" page's switcher links to "/articles/", "/es/articles/" and "/zh/articles/"

  Scenario: A page that exists in one language draws no switcher
    Given the English article "the-other" titled "Another story" is published
    When its Spanish translation "el-sonido" is published
    Then the English "articles/the-other/index.html" page has no language switcher

  Scenario: A site that serves one language draws none and the engine says nothing about languages
    Given the site serves English only
    Then the English "index.html" page has no language switcher
    And the English "index.html" page's skip link says "Skip to main content"

  Scenario: The switcher sits in the masthead by default, after the navigation
    When its Spanish translation "el-sonido" is published
    Then the English "articles/the-sound/index.html" page has its language switcher inside the masthead after the navigation

  Scenario: A site can put the switcher above the footer instead
    Given the site sets its language switcher placement to "footer"
    When its Spanish translation "el-sonido" is published
    Then the English "articles/the-sound/index.html" page has its language switcher above the footer and none in the masthead

  Scenario: A site can ask for a quiet switcher
    Given the site sets its language switcher prominence to "quiet"
    When its Spanish translation "el-sonido" is published
    Then the English "articles/the-sound/index.html" page has a quiet language switcher

  Scenario: A site that draws its own switcher turns the core one off and places the component itself
    Given the site sets its language switcher placement to "none"
    When its Spanish translation "el-sonido" is published
    Then the English "articles/the-sound/index.html" page has no language switcher
    And the site's hook can still read the markup core would draw as the page's language_switcher, which is empty

  Scenario: An unknown placement or prominence is refused when the settings are read
    Given the site sets its language switcher placement to "sidebar"
    When the multilingual site is projected
    Then the projection is refused naming "site.languageSwitcher.placement"

  Scenario: Every public language needs the word for "Language", so the switcher is never named in another language's words
    Given the Spanish interface strings lack "switcherLabel"
    When the multilingual site is projected
    Then the projection is refused naming "es-419: switcherLabel"

  Scenario: The primary language needs it too
    Given the English interface strings lack "switcherLabel"
    When the multilingual site is projected
    Then the projection is refused naming "en: switcherLabel"

  Scenario: A site that turns the switcher off does not need the word in any language
    Given the site sets its language switcher placement to "none"
    And the English interface strings lack "switcherLabel"
    And the Spanish interface strings lack "switcherLabel"
    When the multilingual site is projected
    Then the projection is accepted

  Scenario: The switcher is keyboard operable and closes from the keyboard
    When its Spanish translation "el-sonido" is published
    Then the English "articles/the-sound/index.html" page's switcher is a details control with a summary that opens it from the keyboard
    And every option of it is a link
    And the page loads the language switcher script, which closes the list on Escape and on a click outside
    And the site publishes that script

  Scenario: Switching is a link, so it works without a script
    When its Spanish translation "el-sonido" is published
    Then the English "articles/the-sound/index.html" page's switcher needs no script to open or to follow an option
