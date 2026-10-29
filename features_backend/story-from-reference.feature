Feature: A story based on a Reference is linked to it and written in our own words
  The automated newsroom makes stories from References: a monitor finds a page, an editor or the newsroom decides it deserves
  a story, and the story is written. Two things are true of every such story, whichever path made it. First, the story is
  linked to the Reference it is based on, by the lineage ids of both, so the link survives new versions of either one. The
  newsroom story view lists the Reference with its title, site and preview image and a link that opens it, and the Reference
  view lists the stories based on it. Second, the story has its own content. Its text is ours: either the cited body of a story
  draft that the newsroom wrote, or a brief for the copywriter. It goes through the copywriting and copy-editing stages and is
  never a copy of the Reference's captured text. A save that would put a long verbatim span of the Reference's text into the
  story is refused. The one thing a story may borrow is the image: a post is seeded with the Reference's preview image, which
  stays a remote address credited to its site until the illustration stage replaces it or hosts a licensed copy. Stories that
  were made before this rule existed can be linked afterwards by the web address their text already contains.

  Background:
    Given a Reference "Clef decision models" from the site "blog.example.com" with a preview image and captured text

  Scenario: Promoting a record links the story to its Reference and does not copy the Reference's text
    Given the Reference is a delivered model record
    When an editor promotes the record to the section "models"
    Then the story is linked to the Reference as "based_on"
    And the Reference lists that story among the stories based on it
    And the story's body does not contain the Reference's captured text

  Scenario: Promoting a story draft links the story and seeds the draft's own body
    Given an approved story draft that cites the Reference and says "A router picks the model for each request."
    When the newsroom turns the story draft into a story in the section "articles"
    Then the story is a draft at the copywriting stage
    And the story's body starts with "A router picks the model for each request."
    And the story is linked to the Reference as "based_on"

  Scenario: A story made from a Reference without a draft starts from a brief, not from the source
    When the newsroom starts an article from the Reference without a body
    Then the story's body is a brief for the copywriter that links the source
    And the story's body does not contain the Reference's captured text

  Scenario: A post is seeded with the Reference's preview image but not its text
    When the newsroom starts a post from the Reference with its own body "We read the report and asked what it means for small teams."
    Then the post's body starts with an image from the preview, credited to "Example Blog"
    And the image stays the remote preview address and is not copied into the site's media
    And the story's body does not contain the Reference's captured text

  Scenario: An article is not given the preview image
    When the newsroom starts an article from the Reference with its own body "We read the report and asked what it means for small teams."
    Then the story's body has no image

  Scenario: A body copied from the Reference's text is refused
    When the newsroom tries to start an article whose body repeats a sentence of the Reference's captured text
    Then the save is refused because the body is copied from the Reference
    And no story and no link were written

  Scenario: A short quotation shared with the source is allowed
    When the newsroom starts an article from the Reference with its own body "The router matches the largest model on most prompts, they say."
    Then the story is saved

  Scenario: A later citation does not weaken the link
    Given the newsroom started an article from the Reference with its own body "We read the report."
    When the copywriter cites the Reference in the story
    Then the story is still linked to the Reference as "based_on"

  Scenario: An existing story is found by the web address in its text and linked
    Given an existing draft article "Cloudflare Clef decision models" whose body links to the Reference's address with tracking parameters
    When the operator links references for the site "anth-us" as a dry run
    Then the dry run reports that "Cloudflare Clef decision models" would be linked to the Reference as "based_on"
    And the dry run wrote no link
    When the operator links references for the site "anth-us"
    Then the story is linked to the Reference as "based_on"
    And running it again writes nothing new
