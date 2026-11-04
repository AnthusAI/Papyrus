Feature: Images and citations are on for every Papyrus site
  A Story may carry a picture (::image) and cite a source ([@key] and ::citations) on any Papyrus
  site, with nothing declared in its web/projection.json. Both are on unless the site turns them
  off with "images": false or "citations": false. Declaring "images" as an object still sets the
  widths, formats and layouts of the site's pictures.

  What a body may contain is decided once, from the site's settings and its media store, and read by
  both the save and the projection that makes the page live. A body the page cannot be made from is
  refused when it is saved, with the reason, and never reaches the publish that would have failed
  with "data published, page not live". A site with no media bucket cannot show a picture, and says
  so at save. A page that uses neither feature renders exactly as it did before they were on by
  default.

  Scenario: A site that declares nothing publishes a Story with a picture and a citation
    Given a Papyrus site whose projection.json declares no images and no citations
    And the Story's pictures are uploaded to the site's media store
    When the Story with a picture and a citation is saved
    Then the save is accepted
    When the site renders the Story
    Then the page shows the chart as a responsive picture from the site's renditions
    And the page lists the source the Story cites

  Scenario: A site that turned images off is told at save, not at publish
    Given a Papyrus site whose projection.json turns images off
    When the Story with a picture and a citation is saved
    Then the save is refused with "Unknown directive 'image'" and the note that the site turned images off
    And rendering the Story would have been refused as well

  Scenario: A site that turned citations off is told at save
    Given a Papyrus site whose projection.json turns citations off
    When a Story that cites a source is saved
    Then the save is refused with the note that the site turned citations off

  Scenario: A site with no media bucket says so at save
    Given a Papyrus site whose projection.json declares no images and no citations
    And the site has no media store
    When the Story with a picture and a citation is saved
    Then the save is refused with "no media store"
    And rendering the Story would have been refused as well
    When a Story with only words is saved
    Then the save is accepted

  Scenario Outline: Save and publish give the same verdict
    Given a Papyrus site whose projection.json <declares>
    And the Story's pictures are uploaded to the site's media store
    When the Story <body> is saved
    Then the save verdict is the verdict of rendering the Story

    Examples:
      | declares                           | body                     |
      | declares nothing                   | with only words          |
      | declares nothing                   | with a picture           |
      | declares nothing                   | that cites a source      |
      | turns images off                   | with a picture           |
      | turns images off                   | that cites a source      |
      | turns citations off                | that cites a source      |
      | turns citations off                | with a picture           |
      | declares its own image widths      | with a picture           |

  Scenario: The newsroom's save refuses a picture on a site that turned images off
    Given the content actions of a Papyrus site that turned images off
    When the editor saves a Story with a picture as a draft
    Then the save response fails because the site turned images off
    And nothing is saved

  Scenario: A page that uses neither feature is the same page
    Given a Papyrus site whose projection.json declares no images and no citations
    And a Papyrus site whose projection.json turns images and citations off
    When both render a Story with only words and a link to a picture elsewhere
    Then the two pages are identical

  # The post-deploy render (ReprojectOnDeploy) runs after every backend deploy. A Story that cannot be
  # rendered is the Story's problem, not the deploy's: it is reported and the others are rendered.
  Scenario: A Story with bad markup does not fail the deploy
    Given a Papyrus site whose projection.json turns images off
    And three published Stories, one of which has a picture the site cannot render
    When the post-deploy render runs
    Then the render succeeds and writes the two Stories that can be rendered
    And the report names the Story that could not be rendered and why
    And the drift count the alarm watches is not zero
    And the page the bad Story had before is still there

  Scenario: A failure of the platform still fails the deploy
    Given a Papyrus site whose projection.json declares no images and no citations
    And the page store fails while the post-deploy render writes
    When the post-deploy render runs
    Then the render fails with the storage error

  Scenario: A rollback cannot get stuck on content
    Given the deploy token of the previous deploy was "job-9"
    When CloudFormation rolls the render resource back to the token "job-8" and the render function fails
    Then the resource update succeeds without invoking the render function

  Scenario: A new deploy whose render function fails still fails
    Given the deploy token of the previous deploy was "job-9"
    When CloudFormation updates the render resource to the token "job-10" and the render function fails
    Then the resource update fails with the render function's error

  Scenario: A picture whose renditions were never made is refused at publish, before any data is written
    Given the content actions of a Papyrus site that declares no images, whose media store holds no renditions
    When the editor saves a Story with a picture as a draft
    Then the save is accepted by the site
    When the editor publishes the saved Story
    Then the publish response fails with "page-not-renderable"
    And nothing is published

  Scenario: A broken Story beside good ones reaches no listing, feed or index of the deploy render
    Given a section with an introduction and two good Stories, whose introduction and one more Story are then broken
    When the post-deploy render runs on that site
    Then the render succeeds
    And the report names both broken Stories
    And the broken Story's own page is as it was
    And the section listing, the feeds, the sitemap and the llms files are written with the good Stories
    And the section listing has lost only its introduction

  Scenario: Saving a published Story in place checks its page before writing
    Given the content actions of a Papyrus site that declares no images, whose media store holds no renditions
    And a Story that is published with only words
    When the editor saves that published Story in place with a picture
    Then the save response fails with "page-not-renderable"
    And the published Story is unchanged
