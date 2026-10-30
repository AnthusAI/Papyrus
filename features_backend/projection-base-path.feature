Feature: A standard site projected under a base path
  A site that sets urls.basePath in projection.json lives entirely under that path, so one route on a
  host site's CDN can serve it (dataparade.io/posts) and nothing collides with the host's own files.
  Papyrus puts every page and file it generates under the base path and builds every URL it generates
  with it. Paths an author writes (nav links, redirects, aliases, links in article bodies) are request
  paths and are taken as written. The not-found page and robots.txt are files of the whole host, so
  they stay at the bucket root.

  Background:
    Given a standard site with url style "directory", production URL "https://example.com" and base path "/posts"
    And a published item "hello" with the tag "privacy"

  Scenario: Pages and files are stored under the base path
    When the based site is projected
    Then the based site has these pages: "posts/index.html, posts/hello/index.html, posts/tags/privacy/index.html, posts/css/site-theme.css"
    And every object of the based site outside "_papyrus/" is under "posts/" except "404.html, robots.txt"

  Scenario: Generated links point under the base path
    When the based site is projected
    Then every root-relative href and src in "posts/hello/index.html" starts with "/posts/"
    And every root-relative href and src in "404.html" starts with "/posts/"
    And the based page "posts/hello/index.html" says "<link rel="canonical" href="https://example.com/posts/hello/">"
    And the based page "posts/index.html" says "href="/posts/hello/""

  Scenario: Feeds, sitemap, public data and agent files use the base path
    When the based site is projected
    Then the based page "posts/feed.xml" says "https://example.com/posts/hello/"
    And the based page "posts/sitemap.xml" says "<loc>https://example.com/posts/hello/</loc>"
    And the based page "robots.txt" says "Sitemap: https://example.com/posts/sitemap.xml"
    And the based page "posts/_data/latest.json" says ""/posts/hello/""
    And the based page "posts/llms.txt" says "(https://example.com/posts/hello/index.md)"

  Scenario: Paths the author writes are taken as written
    Given the based site has a nav link "Home" to "/"
    And the item "hello" has the alias "/posts/old-hello/"
    When the based site is projected
    Then the based page "posts/hello/index.html" says "href="/""
    And the based site redirects "/posts/old-hello/" to "/posts/hello/"

  Scenario: A redirect left from another layout never shadows a page
    Data Parade, 2026-10-30: a rollback projected the site under its old base path and left exact
    redirects from the new paths to the old ones. A redirect whose source is a page now would loop
    with the redirect that points at that page, so projecting everything deletes it.
    When the based site is projected
    And the redirect store maps "/posts/hello/" to "/articles/hello/" from an earlier layout
    And everything on the based site is projected again
    Then the based site does not redirect "/posts/hello/"
    And the based site has these pages: "posts/hello/index.html"

  Scenario: The knowledge snapshot is read from the base path and left alone by the reconcile
    Given the based site has a knowledge page and a snapshot stored under "posts/_data/knowledge/"
    When the based site is projected
    And the based site is reconciled
    Then the based page "posts/knowledge/index.html" says "papyrus-knowledge-count">7<"
    And the based site still holds "posts/_data/knowledge/index.json, posts/_data/knowledge/clusters.json, posts/_data/knowledge/entities/acme-loom.json"
    And the based site does not own "posts/_data/knowledge/index.json"
    And the based site holds no snapshot file at the bucket root

  Scenario: A base path must be a lowercase path
    When the settings of a site with base path "/Posts here" are read
    Then they are refused with a message that names "urls.basePath"

  Scenario: The image pipeline does not take a base path yet
    When the settings of a site with base path "/posts" and an images section are read
    Then they are refused with a message that names "urls.basePath"
