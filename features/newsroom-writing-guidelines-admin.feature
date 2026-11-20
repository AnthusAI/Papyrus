Feature: Admins keep the publication's writing guidelines in Administration as guideline files, with a tab for each section
  Under Administration, Policies, an admin opens "Writing guidelines" to say how the publication writes. The guidelines are a set of files, one folder for each
  guideline with a GUIDELINE.md in it: flat front matter, then the prose. A field file has a fixed name (tone, audience, lexicon, glossary, voice examples...)
  and is part of the house style. A rule file has any other name and a severity: an error or a warning derives one editorial check, guidance derives none.
  The page lists the set's files and says for each its severity, whether it changed, and the check it derives; an admin opens a file to edit its front matter
  and body, adds a field file or a rule file, removes one, and Accepts the set as a new version or Rejects the changes. There is a Site tab and one tab for each
  section. A section tab holds only that section's files, laid over the site's, and shows in words where every field in effect came from: the site, this
  section, or locked by the site. Every save is a new version that needs a reason, and the history shows who, when and why. Editors see the same page read only.
  The page uses flat colours and rounded shapes, Lucide icons only, and says every state in words as well as with an icon. These scenarios run the real page in a
  browser, at 1440 and 375 pixels wide, on an in-memory stand-in for the guidelines door that keeps sets of files: no network, nothing written anywhere.

  Scenario: The page lists the guideline files and says what each one does
    Given the writing guidelines page of a publication that has site guidelines
    When the admin looks at the files of the site's guidelines
    Then every field file and every rule file is listed by name, marked as a field file or a rule file
    And each file says its severity in words: error, warning or guidance
    And a rule that derives a check names it and says whether it is on, and a rule with only prose says it needs judgement
    And a field the site locks says in words that sections cannot change it
    And opening a rule file shows its description, severity, words to avoid, patterns and body

  Scenario: An admin edits one file and saves a new version, and every other file is carried over byte for byte
    Given the writing guidelines page of a publication that has site guidelines
    When the admin changes the tone file, looks at what would change, gives a reason and accepts
    Then the preview names the file that changed and the field that changed
    And the page says it saved version 2 and the save names the version it replaces
    And the set is sent as files, and every file the admin did not touch is sent exactly as it was read
    And the history lists both versions with who, when and why
    And picking two versions shows what changed between them in words

  Scenario: An admin adds, edits, removes and rejects rule files
    Given the writing guidelines page of a publication that has site guidelines
    When the admin adds a rule file, fills in its severity, words to avoid, longest text and prose, removes another rule file and rejects a change to a third
    Then a name that is not lowercase words joined by hyphens, is a field file's name or is already taken is refused in words
    And a new rule starts as guidance and says a check is derived when it is saved as an error or a warning
    And a file that is refused when saved shows the problem under that file, naming the key
    And a rejected change puts the saved file back, and a removed file says it is deleted when the admin accepts
    And the preview lists the added and removed files and the check that would be created
    And the saved rule file has its front matter written in the file form and the removed file is gone from the set

  Scenario: An admin adds a section's files and sees which fields come from the site
    Given the writing guidelines page of a publication that has site guidelines
    When the admin opens a section tab, adds a tone file and a lexicon file, and accepts with a reason
    Then the section's set holds only its own files, with the section as their scope, and none of the site-only files is offered
    And the In effect page says for every field whether it came from the site, this section or both
    And prose and word lists show the site's lines first and the section's after them

  Scenario: A locked field cannot be added on a section tab
    Given the writing guidelines page of a publication that has site guidelines
    When the admin opens a section tab
    Then a field the site locks says "Locked by site" and is not offered as a file to add
    And a field the site leaves open can be added and shows the site's value as a hint
    And on the Site tab the same field can be changed and says in words that sections cannot change it

  Scenario: An editor sees the guidelines read-only
    Given the writing guidelines page of a publication that has site guidelines
    When an editor opens the page
    Then the page says in words that it is read only
    And every box is disabled and there is no save button, no way to add or remove a file and no Story picker
    And the history can still be read

  Scenario: Saving without a reason is not possible, and all changes can be rejected
    Given the writing guidelines page of a publication that has site guidelines
    When the admin changes a file and gives no reason, or only blank spaces
    Then the save button stays off and the page says a reason is needed
    And Reject all changes puts the saved set back and the page says no file has changed
    And nothing is sent to be saved

  Scenario: An admin picks a published Story as a voice example
    Given the writing guidelines page of a publication that has site guidelines
    When the admin opens the voice examples file, searches the published Stories, picks one, says what it shows and saves
    Then the picker narrows to the matching Stories
    And the saved voice examples file lists the Story with the note

  Scenario: A publication with no guidelines yet is told so, and the checks drawn from them are listed with a link
    Given the writing guidelines page of a publication that has no site guidelines
    Then the page says the publication has no writing guidelines yet
    And the first save expects no earlier version and makes version 1
    Given the writing guidelines page of a publication that has site guidelines
    Then only the editorial checks drawn from these guidelines are listed, with a link to Editorial checks
