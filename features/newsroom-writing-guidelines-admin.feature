Feature: Admins keep the publication's writing guidelines in Administration, with a tab for each section
  Under Administration, Policies, an admin opens "Writing guidelines" to say how the publication writes: its voice, audience, tone, words to prefer and avoid,
  glossary, binding rules and published Stories that show the voice. There is a Site tab and one tab for each section. A section tab adds to the site's
  guidelines and shows, in words, where every field in effect came from: the site, this section, or locked by the site. Every save is a new version that needs a
  reason, and the history shows who, when and why, with the difference between any two versions. Editors see the same page read only. The page uses flat colours
  and rounded shapes, Lucide icons only, and says every state in words as well as with an icon. These scenarios run the real page in a browser, at 1440 and 375
  pixels wide, on an in-memory stand-in for the guidelines door: no network, nothing written anywhere.

  Scenario: An admin edits the site's writing guidelines and sees a new version in history
    Given the writing guidelines page of a publication that has site guidelines
    When the admin changes the tone, looks at what would change, gives a reason and saves
    Then the page says it saved version 2 and the save names the version it replaces
    And the binding rules are carried over untouched
    And the history lists both versions with who, when and why
    And picking two versions shows what changed between them in words

  Scenario: An admin adds a section override and sees which fields come from the site
    Given the writing guidelines page of a publication that has site guidelines
    When the admin opens a section tab, adds a tone and a word to avoid, and saves with a reason
    Then the section's document holds only its additions, without the site's locks or binding rules
    And the In effect page says for every field whether it came from the site, this section or both
    And prose and word lists show the site's lines first and the section's after them

  Scenario: A locked field cannot be changed on a section tab
    Given the writing guidelines page of a publication that has site guidelines
    When the admin opens a section tab
    Then a field the site locks says "Locked by site" and cannot be edited
    And a field the site leaves open can be set and shows the site's value as a hint
    And on the Site tab the same field can be changed and says in words that it is locked

  Scenario: An editor sees the guidelines read-only
    Given the writing guidelines page of a publication that has site guidelines
    When an editor opens the page
    Then the page says in words that it is read only
    And every box is disabled and there is no save button and no Story picker
    And the history can still be read

  Scenario: Saving without a reason is not possible
    Given the writing guidelines page of a publication that has site guidelines
    When the admin changes a field and gives no reason, or only blank spaces
    Then the save button stays off and the page says a reason is needed
    And nothing is sent to be saved

  Scenario: An admin picks a published Story as a voice example
    Given the writing guidelines page of a publication that has site guidelines
    When the admin searches the published Stories, picks one, says what it shows and saves
    Then the picker narrows to the matching Stories
    And the saved document lists the Story with the note

  Scenario: A publication with no guidelines yet is told so, and the checks drawn from them are listed with a link
    Given the writing guidelines page of a publication that has no site guidelines
    Then the page says the publication has no writing guidelines yet
    And the first save expects no earlier version and makes version 1
    Given the writing guidelines page of a publication that has site guidelines
    Then only the editorial checks drawn from these guidelines are listed, with a link to Editorial checks
