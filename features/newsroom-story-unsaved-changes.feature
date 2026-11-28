@brand-agnostic @story-unsaved-changes
Feature: An editor has one Save, and always sees Save and Cancel while a Story has unsaved changes
  Nothing in the Story editor saves by itself. There used to be two buttons, Save draft and Save as new version, and nobody could tell them apart;
  on a live Story, Save draft even republished the page at once. Now there is one Save. A draft is saved in place. A live Story is saved as a new
  draft version, so readers keep seeing the live page until that version is published. The toolbar's Save sits at the very top, and in the drawer that
  opens from a Stories board card the Title, Subtitle and Blurb fields are far below it, under the schedule, the rating, the headline picture and the
  view switch. So while a Story has unsaved changes, a bar stays pinned to the bottom of whatever scrolls, the drawer or the page, saying so, with
  Cancel, which puts back the text as it was last saved, and Save. When saving is off, the bar says why in words. A field that cannot take an edit,
  because the Story's front matter is not YAML the fields can read, is switched off with a note saying so, instead of looking editable while it
  silently drops what is typed. Closing the drawer, or opening another Story from the board, asks before it throws unsaved changes away. These
  scenarios use the local preview data in an isolated browser at 375 and 1440 pixels and never touch production.

  Scenario: Editing the subtitle in the drawer shows Save and Cancel pinned in view, and saving keeps the change
    Given the Stories board with a draft Story
    When the editor opens the draft Story and changes its subtitle
    Then a bar saying "Unsaved changes" with Cancel and Save is in view at the bottom of the drawer, and the toolbar has one Save button
    And pressing Save saves the Story once, in place, keeps the new subtitle and the bar goes away

  Scenario: Cancel puts back the subtitle as it was last saved
    Given the Stories board with a draft Story
    When the editor opens the draft Story, changes its subtitle and presses Cancel
    Then the subtitle is as it was last saved, nothing was saved and the bar goes away

  Scenario: Saving a live Story makes a new draft version and leaves the live page alone
    Given the Story editor open on a published Story
    When the editor changes its subtitle and presses Save in the bar
    Then the bar said that saving makes a new draft version that readers see once it is published
    And the Story was saved once as a new version, never in place, nothing was published, and the editor shows the new draft version

  Scenario: A Story whose front matter the fields cannot read says so instead of dropping what is typed
    Given the Stories board with a Story whose front matter is not valid YAML
    When the editor opens that Story on the Edit view
    Then Title, Subtitle and Blurb are switched off and a note says to fix the front matter under Front matter (YAML)

  Scenario: Closing the drawer asks before it throws unsaved changes away
    Given the Stories board with a draft Story
    When the editor changes the subtitle of the draft Story and closes the drawer
    Then the editor is asked whether to discard the changes, and answering no keeps the drawer open with the change
    And answering yes closes the drawer

  Scenario: On a phone the bar fits and nothing scrolls sideways
    Given the Stories board with a draft Story
    When the editor opens the draft Story on a phone and changes its subtitle
    Then the bar with Cancel and Save is in view at the bottom of the screen and nothing scrolls sideways
