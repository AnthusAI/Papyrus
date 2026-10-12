Feature: Image renditions made once at media upload
  When an image is uploaded to the media store, its responsive renditions, a
  listing copy and a small description of the set are written to the site store
  at the paths the full Markus build uses. A page render then reads that
  description instead of opening or encoding any image.

  Scenario: Renditions made at upload are byte-identical to the full build
    Given a pictured article and its images are published
    When the images are uploaded and renditions are made
    Then every rendition file equals the file the full build writes
    And the description of each image is written after its rendition files

  Scenario: The listing copy of a wide image is downscaled like the full build staging
    Given a pictured article and its images are published
    When the images are uploaded and renditions are made
    Then the listing copy of "images/wide.jpg" is 600 pixels wide
    And the listing copy of "images/small.png" is byte-identical to the original

  Scenario: Projecting a page with images equals the full build and opens no image
    Given a pictured article and its images are published
    And the images are uploaded and renditions are made
    When I project the pictured site to a local directory
    Then the projected pages are identical to the pages of the full build
    And no image was opened while projecting

  Scenario: A page that references an image without renditions fails loudly
    Given a pictured article and its images are published
    When I project the pictured article before any renditions exist
    Then the projection reports an error naming "images/wide.jpg" and the renditions command

  Scenario: Renditions follow the legacy pipeline too
    Given a pictured article and its images are published with the legacy image pipeline
    When the images are uploaded and renditions are made
    And I project the pictured site to a local directory
    Then every rendition file equals the file the full build writes
    And the projected pages are identical to the pages of the full build

  Scenario: Objects that are not images under media are ignored
    Given the renditions function is configured for the fixture site
    When the object "media/notes/readme.txt" is created
    Then nothing is written to the site store

  Scenario: An upload event makes the renditions of the uploaded image
    Given the renditions function is configured for the fixture site
    And the media store holds the fixture images
    When the object "media/images/wide.jpg" is created
    Then the site store holds the description of "images/wide.jpg"

  Scenario: A back-fill dry run reports what it would make and writes nothing
    Given the renditions function is configured for the fixture site
    And the media store holds the fixture images
    When I back-fill renditions with a dry run
    Then the report covers 3 images and counts action "would-render" 3
    And nothing is written to the site store

  Scenario: Back-filling is idempotent
    Given the renditions function is configured for the fixture site
    And the media store holds the fixture images
    When I back-fill renditions
    And I back-fill renditions again
    Then the first report counts action "rendered" 3
    And the second report counts action "skipped-existing" 3

  Scenario: A single image can be requested again
    Given the renditions function is configured for the fixture site
    And the media store holds the fixture images
    And I back-fill renditions
    When I request renditions for "images/wide.jpg"
    Then the report counts action "rendered" 1

  Scenario: With media originals enabled an uploaded object is published as it is
    Given the renditions function publishes media originals
    And the media store holds the fixture images
    When the object "media/notes/readme.txt" is created
    Then the site store holds "notes/readme.txt" equal to the uploaded object

  Scenario: Back-filling media originals covers every object and is idempotent
    Given the renditions function publishes media originals
    And the media store holds the fixture images
    When I back-fill renditions with originals
    And I back-fill renditions with originals again
    Then the first report counts action "copied" 4
    And the second report counts action "skipped-existing" 4
    And the site store holds "images/wide.jpg" equal to the uploaded object

