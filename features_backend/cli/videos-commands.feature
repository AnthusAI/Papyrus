Feature: An operator renders a narrated video from a Story and attaches it
  The `papyrus videos` commands render a narrated video from a Story, using the video configuration and the VideoML tool the
  publication itself supplies, and register the finished MP4 as the Story's lead media. A publication with no video configuration
  is told exactly what is missing instead of getting a half-made video.

  Scenario: Rendering without a video config explains what is missing
    Given a publication directory without a video config
    When I run videos render for the article "sample-article"
    Then the command fails mentioning "Video config not found"
    And the failure mentions "PAPYRUS_VIDEO_CONFIG"

  Scenario: Attaching a rendered video registers it as lead media
    Given a publication with a video config and a rendered video for "sample-article"
    And a CMS item "sample-article"
    When I attach the video for "sample-article"
    Then the item has a lead video media asset stored at "media/videos/sample-article.mp4"
    And the video file was uploaded to the media store

  Scenario: The VideoML CLI is located from the publication's node_modules
    Given a publication with a video config and a rendered video for "sample-article"
    And the publication has @videoml/cli installed in node_modules
    When I resolve the VideoML command
    Then the command runs "npx --no-install vml pipeline"
    And the command runs in the publication directory
