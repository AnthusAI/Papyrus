@backend @reference-video-thumbnails
Feature: Every video Reference shows the video's own thumbnail, kept in our storage
  A card for a video, such as the ones "::include{kind="references" medium="video"}" draws on a videos page, shows the video's own picture. The
  picture's address is worked out from the video itself and not read from the page: YouTube's is built from the video id with no API key and no
  page fetch, and Vimeo, Dailymotion, Loom, Wistia and TED are asked through their public oEmbed address. Twitch has none. The picture is copied
  into the site's own media storage and only that copy is ever published, so a reader's browser never contacts the video platform (before or after
  the cookie banner is answered) and a takedown on the platform does not break the card. YouTube refuses cloud addresses for transcripts and
  nothing has shown that its picture host answers them, so nothing in the cloud fetches a picture: a person signed in with "papyrus login" runs
  "papyrus references capture-thumbnails" on a connection the platforms answer. The first run is the backfill. It previews by default, finds the
  videos through the medium index and not by scanning, does the work once for each video, records "none" for a video the platform has no picture
  for so nobody asks again, and never replaces an image an editor chose. Nothing here touches production: the site, the storage and the
  platforms are all in memory.

  Background:
    Given a site with accepted and pending videos and an ordinary article

  Scenario: A YouTube thumbnail is worked out from the video id alone
    When the thumbnail worker runs with write
    Then the picture was asked for at "https://img.youtube.com/vi/aaaaaaaaaaa/hqdefault.jpg" without opening the video page
    And the picture was copied into the site's media storage under "assets/reference-thumbnails/"
    And the video holds the site path of its copy

  Scenario: Another platform is asked for its thumbnail through oEmbed
    Given a Vimeo video that oEmbed gives a thumbnail for
    When the thumbnail worker runs with write
    Then the Vimeo video was asked about once through its oEmbed address
    And the Vimeo video holds the site path of its copy

  Scenario: A platform with no oEmbed address has no thumbnail and is not asked again
    Given a Twitch video
    When the thumbnail worker runs with write
    And the thumbnail worker runs with write
    Then the Twitch video holds "none"
    And no platform was asked about the Twitch video

  Scenario: YouTube's grey stand-in for a missing picture is never taken
    Given YouTube answers "not found" with its grey 120 pixel picture for the newest video
    When the thumbnail worker runs with write
    Then the newest video holds "none"
    And nothing was copied for the newest video
    And running the thumbnail worker again does not ask YouTube about it

  Scenario: A platform that cannot be reached leaves the video for the next run
    Given YouTube refuses this connection for the newest video
    When the thumbnail worker runs with write
    Then the newest video holds nothing
    And running the thumbnail worker again asks YouTube about it again

  Scenario: The worker stops when the platforms keep refusing this connection
    Given YouTube refuses this connection for every video
    When the thumbnail worker runs with write
    Then the worker stopped after three refusals with a message to run it elsewhere
    And no video holds anything

  Scenario: The first run only previews
    When the thumbnail worker runs
    Then every video that needs a thumbnail was listed as one it would fetch
    And no platform was asked and nothing was copied or recorded

  Scenario: A video is fetched once however often the worker runs
    When the thumbnail worker runs with write
    And the thumbnail worker runs with write
    Then each video was fetched exactly once

  Scenario: The home page publishes our copy and never the platform's address
    Given the page declared a platform picture for the newest video
    And the thumbnail worker has run with write
    When the home page snapshot record of the newest video is built
    Then its image is the site path of the copy
    And its image is not an address on a video platform

  Scenario: A video with no copy yet shows no image even when its page declared one
    Given the page declared a platform picture for the newest video
    When the home page snapshot record of the newest video is built
    Then it has no image

  Scenario: An image an editor chose is never replaced
    Given an editor chose an image for the newest video
    When the thumbnail worker runs with write
    Then the site refused to record a thumbnail for the newest video
    And the home page snapshot record of the newest video has the editor's image

  Scenario: An ordinary page keeps the preview image its page declared
    Given the page declared a preview image for the article
    When the home page snapshot record of the article is built
    Then its image is the page's preview image

  Scenario: A videos page draws the copy from the site, below the base path when there is one
    Given the thumbnail worker has run with write
    When a videos block is drawn for a site under the base path "/posts"
    Then the card for the newest video shows the copy at "/posts/assets/reference-thumbnails/"
