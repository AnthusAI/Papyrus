Feature: Images and media of a site projected under a base path
  A site that sets urls.basePath in projection.json (Data Parade serves /articles from dataparade.io)
  lives entirely under that path, because the host's CDN routes only that path to the site. Images
  and media follow the same rule as pages and stylesheets. The responsive renditions of an image, the
  listing copy, and the original media objects of a site with media.originals are written under the
  base path (articles/assets/responsive/..., articles/assets/<story folder>/...). Every URL a page or
  its head carries for them is root-relative under the base path, or absolute with the site origin
  and the base path, so they load through the public host with no change to the CDN. The image
  source stays the path the story uses: assets/draft-unsectioned-<hash>/chart.png is the media key
  media/assets/draft-unsectioned-<hash>/chart.png without its media/ prefix, locally the file of
  that path in the content directory and in the cloud the media object of that key. A site without
  a base path is unchanged byte for byte. The Markdown twin of a story is its Markus source as
  written, so it names the image by the story's own path and not by a URL.

  Background:
    Given a site under the base path "/articles" with images and media originals
    And a story "hello" with a light and dark chart, a lone picture and a Markdown picture

  Scenario: Renditions and originals are written under the base path and nowhere else
    When the site is projected with the local command
    Then the output holds the renditions of the chart under "articles/assets/responsive/assets/draft-unsectioned-a1b2c3d4/"
    And the output holds the original "articles/assets/draft-unsectioned-a1b2c3d4/chart.png"
    And the output holds nothing under "assets/" and nothing under "assets/responsive/" at its root

  Scenario: Every image URL of the page starts with the base path and exists in the output
    When the site is projected with the local command
    Then every image URL in "articles/hello/index.html" starts with "/articles/assets/responsive/"
    And every image URL in "articles/hello/index.html" is a file of the output at that path

  Scenario: A light and dark pair on a page under the base path
    When the site is projected with the local command
    Then the pictured page "articles/hello/index.html" has a light and a dark variant of the chart
    And both variants use only URLs under "/articles/assets/responsive/"
    And the pictured page "articles/hello/index.html" carries the rule that shows the dark variant only in dark mode
    And the srcset widths of both variants are files of the output

  Scenario: A Markdown picture is made responsive under the base path
    When the site is projected with the local command
    Then the Markdown picture of "hello" is a responsive image whose URLs start with "/articles/assets/responsive/"

  Scenario: Social and structured metadata use the origin, the base path and the first image
    When the site is projected with the local command
    Then the pictured page "articles/hello/index.html" says "<meta property="og:image" content="https://example.com/articles/assets/responsive/"
    And the pictured page "articles/hello/index.html" says "<meta name="twitter:image" content="https://example.com/articles/assets/responsive/"
    And the pictured page "articles/hello/index.html" says ""image":"https://example.com/articles/assets/responsive/"

  Scenario: The Markdown twin keeps the story's own image paths
    When the site is projected with the local command
    Then the pictured page "articles/hello/index.md" says "src="assets/draft-unsectioned-a1b2c3d4/chart.png""
    And the pictured page "articles/hello/index.md" does not say "/articles/assets"

  Scenario: Projecting everything again keeps the images and does not treat them as retired pages
    When the site is projected with the local command
    And the site is reconciled against its output
    Then the reconcile finds no orphan pages and deletes nothing
    And the output still holds the renditions of the chart under "articles/assets/responsive/assets/draft-unsectioned-a1b2c3d4/"

  Scenario: An uploaded image gets its renditions and original under the base path in the cloud
    Given the renditions function is configured for the site
    When the media object "media/assets/draft-unsectioned-a1b2c3d4/chart.png" is uploaded
    Then the site store holds the description "articles/assets/responsive/assets/draft-unsectioned-a1b2c3d4/chart.meta.json"
    And the site store holds the original "articles/assets/draft-unsectioned-a1b2c3d4/chart.png" equal to the uploaded object
    And the site store holds nothing at its root

  Scenario: The cloud render of a story equals the local render
    Given the renditions function is configured for the site
    And every picture of the story is uploaded to the media store
    When the site is rendered from the site store
    And the site is projected with the local command
    Then the pages of the cloud render equal the pages of the local render

  Scenario: Renditions left at the bucket root by an earlier layout are not used
    Given the renditions of the story were made before the base path was set
    When the site is rendered from the site store
    Then the render fails naming "articles/assets/responsive/assets/draft-unsectioned-a1b2c3d4/" and the renditions command

  Scenario: The settings accept a base path together with images and media
    When the settings of a site with base path "/articles", an images section and a media section are read
    Then the pictured settings are accepted

  Scenario: A site without a base path is unchanged
    Given a site without a base path with images and media originals
    And the renditions function is configured for the site
    And every picture of the story is uploaded to the media store
    When the site is rendered from the site store
    Then the pages equal the recorded pages of the site before base paths covered images
    And the site store holds the description "assets/responsive/assets/draft-unsectioned-a1b2c3d4/chart.meta.json"
    And the site store holds the original "assets/draft-unsectioned-a1b2c3d4/chart.png" equal to the uploaded object
