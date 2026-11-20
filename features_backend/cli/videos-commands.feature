Feature: Producing and attaching article videos
  The papyrus videos commands render narrated videos from CMS items using a
  publication-supplied video config, and register the rendered MP4 as media.

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
