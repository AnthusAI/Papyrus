Feature: Each Reference carries the preview its source page declares, so the References feed can show an image and a one-line dek
  The References feed is a news page: every card has a picture, a title, a one-line dek and the source's name. They are not made up
  and not copied. Papyrus reads the source page the way a link preview does (its og:image or twitter:image, its description and its
  site name) through link exploration, and stores the result as one preview attachment on the Reference. The image address is kept,
  not the image: the browser loads it straight from the source with no referrer. Only public http and https pictures are accepted,
  so a data address, a local address or a login in the address is never stored. A page that declares nothing is recorded as checked.
  Running the command again skips References that already have a preview, and a dry run reads and counts without writing.

  Scenario: A page's own preview is read when its link is explored
    Given a source page that declares the image "/img/hero.jpg", the description "Regulators approved a scheme." and the site name "Publisher"
    When the source page is explored
    Then the exploration returns the image "https://www.publisher.example/img/hero.jpg", the description and the site name

  Scenario: Only a public web picture is ever kept
    Given a source page that declares the image "data:image/png;base64,AAAA"
    When the source page is explored
    Then the exploration returns no image

  Scenario: Enrichment stores one preview attachment per Reference and skips the ones that have it
    Given three References, one of which already has a preview attachment
    When the preview enrichment runs
    Then a preview attachment is written for each of the other two
    And the Reference that already had one is not read again

  Scenario: A dry run reads and counts without writing
    Given three References, one of which already has a preview attachment
    When the preview enrichment runs as a dry run
    Then no preview is written
    And the counts say how many would have been written
