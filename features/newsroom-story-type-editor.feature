@story-type-editor
Feature: A Story's type is a field the editor sets, from the types the site defines
  Papyrus lists no Story types. A site declares the types it offers, and the one a new Story gets, in its projection.json (storyTypes); a site that declares
  nothing offers the article type and the types it gives a URL base. In the Story the editor sees those types as buttons, never a dropdown, with a check mark
  on the chosen one so that colour is not the only signal. A Story's type can change after it is created, and that follows versioning: a new version carries
  the new type. A live Story keeps its address until that version is published; saving it in place would republish it at once, so that is off, and the editor
  says what publishing will do. A type the site gives no address (no urls.types entry, no section route) says plainly, in the Story, that it has no public URL.

  Scenario: The site's types are buttons, with the default chosen
    Given a Story open in the editor on a site that offers the types article, post and guide
    When the editor chooses the Post button
    Then the types are buttons with a check on the chosen one, there is no dropdown, and the Story is now a post under the posts address

  Scenario: A type with no address says it has no public URL
    Given a Story open in the editor on a site that offers the types article, post and guide
    When the editor chooses the Guide button
    Then the editor says in plain words that the Story has no public URL, and choosing Post takes the note away

  Scenario: A live Story changes type through a new version
    Given a published Story open in the editor on a site that offers the types article, post and guide
    When the editor chooses Post, saves a new version and publishes it
    Then saving in place was off, the live address stayed until the new version was published, and publishing said that the address moved

  Scenario: A live Story cannot be published as a type with no page
    Given a published Story open in the editor on a site that offers the types article, post and guide
    When the editor saves a new version of it as a Guide
    Then Publish is off and the editor says it would remove the live page

  Scenario: A site that declares nothing offers the article type
    Given a Story open in the editor on a site that declares no Story types
    Then only the article type and the page are offered

  Scenario: On a phone the type buttons are large targets
    Given a Story open in the editor on a phone
    Then every type button is at least forty pixels tall and nothing scrolls sideways
