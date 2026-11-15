Feature: Admins choose which languages are public, and how each is served, under Administration, Editorial checks
  Under Administration, Editorial checks, Settings, an admin lists the languages the site writes in. For every enabled language other than the primary the form
  then shows three controls: whether the language is public, its web address prefix and how its page addresses (slugs) are made. An enabled language that is not
  public is written, translated and checked but gets no page on the public site; the primary language is always public. The prefix shows its default and the slug
  policy shows its default. The rules these settings must obey are the projection's own, checked by the server as the admin edits, so a refusal is read before
  anything is saved. Saving keeps every setting the form does not edit. The page uses flat colours and rounded shapes and says every state in words. These
  scenarios run the real page in a browser, at 1440 and 375 pixels wide, on an in-memory stand-in for the editorial checks door: no network, nothing written anywhere.

  Scenario: An admin makes a language public and saves
    Given the editorial checks settings of a site that writes in English, Latin American Spanish and Chinese, with only English public
    When the admin makes Latin American Spanish public and saves the settings
    Then the page says the settings were saved
    And the saved languages list English first and then Latin American Spanish as public
    And the saved languages keep every key the form does not show, and the house guidance is unchanged

  Scenario: An admin sets a prefix and a slug policy and sees the defaults
    Given the editorial checks settings of a site that writes in English, Latin American Spanish and Chinese, with only English public
    When the admin looks at the controls for Latin American Spanish and Chinese
    Then each prefix shows its default and says which address the pages live under
    And each slug policy shows its default, translated for Spanish and the title's own script for Chinese
    When the admin gives Latin American Spanish the prefix "latam" and the slug policy of the original story's address, and saves
    Then the saved languages hold only that prefix and that slug policy, and no public list

  Scenario: A setting the server refuses is shown before saving and cannot be saved
    Given the editorial checks settings of a site that writes in English, Latin American Spanish and Chinese, with only English public
    When the admin gives Latin American Spanish the prefix that Chinese already uses
    Then the page says in words that the two languages would both be served under the same address
    And the save button is off and nothing is saved
    And the admin can still correct the prefix, and the message goes away and the save button comes back

  Scenario: Saving another setting leaves the language serving keys as they were stored
    Given the editorial checks settings of a site whose Spanish is public with its own prefix and whose Chinese uses pinyin slugs
    When the admin changes only the house guidance and saves
    Then the saved languages are exactly the languages that were stored

  Scenario: Taking a language out of the list takes its public flag, prefix and slug policy with it
    Given the editorial checks settings of a site whose Spanish is public with its own prefix and whose Chinese uses pinyin slugs
    When the admin removes Chinese from the languages the site writes in and saves
    Then the saved languages no longer mention Chinese anywhere
    And the Spanish settings are kept
