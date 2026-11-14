Feature: An editor finds a stock cover image for a Story, four at a time
  On a saved Story the editor presses "Cover image" and sees four royalty-free pictures from Wikimedia Commons, each with its creator, licence and
  a link to its file page. With no search words the system works out what to look for from the Story's title and summary, with no paid model, and
  says what it searched for. The editor can accept one picture, reload for four more, type their own words and search, or give up. Pictures already
  shown never come back in the same run. Accepting copies the picture into the site's own media storage through the same upload as "Insert image",
  so public pages never load from Wikimedia, and it puts the picture in the draft as the Story's cover with its credit; saving the draft creates the
  new Story version. Only a signed-in editor or administrator can use the search. These scenarios run the real code against recorded-shape
  synthetic answers; nothing here contacts Wikimedia.

  Scenario: The picker offers four options with their credit
    Given a Story whose title and summary are about offshore wind
    When the editor opens the cover picker without typing anything
    Then four options are shown, each with its creator, licence and file page link
    And the picker says what it searched for and that the words came from the Story

  Scenario: Reload shows four new options and never repeats a picture
    Given the picker has shown four options
    When the editor presses reload
    Then the next four options come from further down the same results
    And none of the pictures already shown is offered again

  Scenario: The editor searches with their own words
    Given the picker has shown four options
    When the editor types search words and presses Search
    Then the picker searches for those words and the typed words stay in the text box

  Scenario: Loading, nothing found and failure each say so in words
    Given the picker is waiting for Wikimedia Commons
    When there is nothing to show, or the search fails
    Then the picker says it is looking, or that nothing was found with a licence we can use, or what went wrong
    And the words the editor typed are kept
    And a failed search can be tried again

  Scenario: Only royalty-free pictures with a known creator and licence are offered
    Given Wikimedia Commons answers with files of many licences
    When the answers are read
    Then public domain, CC0 and CC BY pictures with a creator and a licence address are offered
    And share-alike, non-commercial, no-derivatives, non-free and unknown licences are never offered
    And a file with restrictions, no creator, a small size or an unaccepted type is never offered

  Scenario: The search follows Wikimedia's rules for programs
    Given a search that needs more than one request
    When the requests are made
    Then they go one after another, name the client and its contact in the User-Agent, ask the API to report load, and stop with a retry hint when Wikimedia says it is busy
    And an identical request within ten minutes is answered from memory

  Scenario: Only editors and administrators can search or copy
    Given the cover search route
    When someone without a valid sign-in, or a signed-in reader, calls it
    Then it answers that sign-in as an editor is needed and never reaches the image source
    And an editor and an administrator are served

  Scenario: Copying a picture in checks it first
    Given an editor accepts an option
    When the server copies the picture
    Then the licence is looked up again at the source and the address comes from the source, never from the browser
    And a picture that is not a JPEG, PNG or WebP, is too narrow, is too large, or is not at an allowed Wikimedia host is refused in words

  Scenario: Accepting makes the picture the Story's cover with a credit, and saving makes a version
    Given an editor accepts an option on a saved Story
    When the cover is put in the draft
    Then the body starts with the picture and its credit, the front matter points at the copy and records the author, licence, licence address and file page
    And an earlier stock cover is replaced in place while any other figure, such as a diagram, stays
    And the Night counterpart of the old cover is removed so a photo is shown as it is in dark mode
    And nothing is saved until the editor saves the draft

  Scenario: The credit shows under the picture on the article page and on no card
    Given a Story with a stock cover
    When its pages are built
    Then the article page's figure has the credit directly under the picture
    And no card, listing, feed or data file carries the credit or the cover record
