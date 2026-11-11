Feature: Saving writing guidelines updates the editorial checks drawn from them
  The writer and the checker read the same data. When an admin saves a site's writing guidelines, the Humanus policies drawn from them (the avoided lexicon, the
  banned phrases, the house checks and the rest) are created or updated at publication scope; when an admin saves a section's writing guidelines, desk
  policies are created for that section. A drawn policy records where it came from as writing-guidelines, the document's slug and the saved version. Only
  policies with that source for that very document are ever created, updated or disabled: a starter-pack policy, a policy an admin wrote, and a drawn policy an
  admin has since edited by hand (its source becomes custom) are never changed by a save. Removing a word disables the policy it produced and keeps it for
  history. The diff lists the check changes before anything is saved. The tests run against an in-memory backend that fails on any table scan.

  Scenario: Saving site writing guidelines creates the checks drawn from them
    Given a site with no writing guidelines and no editorial checks
    When an admin saves site writing guidelines that avoid the word "synergy"
    Then a publication check named "avoid-lexicon" exists with the source "writing-guidelines:editorial-doctrine-writing:v1"
    And that check detects the word "synergy"

  Scenario: Saving a new avoided word updates exactly one drawn check
    Given a site whose saved writing guidelines avoid the word "synergy"
    When an admin saves site writing guidelines that avoid the words "synergy" and "leverage"
    Then exactly one check was updated and it is "avoid-lexicon"
    And that check detects the word "leverage"
    And its source names version 2

  Scenario: Saving section writing guidelines creates desk checks for that section
    Given a site whose saved writing guidelines avoid the word "synergy"
    When an admin saves writing guidelines for the section "news" that avoid the word "buzz"
    Then a check named "avoid-lexicon" exists at the scope "news" with the source "writing-guidelines:desk-doctrine-news-writing:v1"
    And the publication check "avoid-lexicon" still detects only the word "synergy"

  Scenario: A check an admin wrote is never changed by saving guidelines
    Given a site with a starter check and a hand-written check both keyed "avoid-lexicon" and "banned-phrases"
    When an admin saves site writing guidelines that ban the phrase "game changer" besides avoiding "synergy"
    Then the starter check and the hand-written check are exactly as they were
    And the save reports both as skipped

  Scenario: Removing a word disables the check it produced and keeps it
    Given a site whose saved writing guidelines avoid the word "synergy"
    When an admin saves site writing guidelines that avoid no words
    Then the check "avoid-lexicon" still exists, disabled, with its history version raised
    And no check was deleted

  Scenario: Editing a derived check by hand stops it being synced
    Given a site whose saved writing guidelines avoid the word "synergy"
    And an admin has edited the check "avoid-lexicon" by hand so its source is "custom"
    When an admin saves site writing guidelines that avoid the words "synergy" and "leverage"
    Then the check "avoid-lexicon" is exactly as the admin left it

  Scenario: The diff shows check changes before anything is saved
    Given a site whose saved writing guidelines avoid the word "synergy"
    When an admin asks for the diff of site writing guidelines that avoid the words "synergy" and "leverage"
    Then the diff lists an update of "avoid-lexicon" at the scope "publication"
    And no check and no guideline version was written
