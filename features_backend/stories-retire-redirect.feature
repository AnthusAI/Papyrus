Feature: Retire a story and redirect its address to another story
  When two stories are merged into one article, the story that goes away still has public
  addresses: people have bookmarked them and other sites link to them. `papyrus stories retire
  --story X --redirect-to Y` takes X down and sends every address X was ever served at, by a
  permanent redirect, to the address Y has now. X moves to the retired stage and keeps every
  version; it leaves the listings, the sitemap and the cross-story boilerplate check. When Y
  later changes address the redirects follow, never forming a chain. `--dry-run` writes
  nothing, and `--undo` brings X back and removes the redirects.

  Background:
    Given a site with the published stories "old-article" and "merged" in articles and "old-post" in notes

  Scenario: Retiring an article redirects its address to the merged article
    When the story "old-article" is retired into "merged"
    Then the site redirect store maps "/articles/old-article.html" to "/articles/merged.html"
    And the page "articles/old-article.html" no longer exists
    And the story "old-article" is in the retired stage and still has its versions
    And a fresh projection of everything finds nothing to change

  Scenario: Retiring a post in another folder redirects to the article's address
    When the story "old-post" is retired into "merged"
    Then the site redirect store maps "/notes/old-post.html" to "/articles/merged.html"
    And the page "notes/old-post.html" no longer exists

  Scenario: The addresses a story had before it was renamed redirect too
    Given the story "old-article" was served at an alias "old/first-address" and then renamed to "old-article-renamed"
    When the story "old-article" is retired into "merged"
    Then the site redirect store maps "/old/first-address" to "/articles/merged.html"
    And the site redirect store maps "/articles/old-article.html" to "/articles/merged.html"
    And the site redirect store maps "/articles/old-article-renamed.html" to "/articles/merged.html"

  Scenario: The Markdown twin of a retired story redirects to the Markdown twin of the target
    Given a site whose pages have Markdown twins
    Then the retired story's "notes/old.md" redirects to "/articles/merged.md"
    And the retired story's "notes/old.html" redirects to "/articles/merged.html"

  Scenario: The listings and the sitemap drop the retired story
    When the story "old-article" is retired into "merged"
    Then the stored pages "index.html" and "articles/index.html" and "sitemap.xml" do not mention "old-article"

  Scenario: A target that is renamed later is followed, without a chain
    Given the story "old-article" is retired into "merged"
    When the story "merged" is renamed to "merged-renamed" and projected
    Then the site redirect store maps "/articles/old-article.html" to "/articles/merged-renamed.html"
    And the site redirect store maps "/articles/merged.html" to "/articles/merged-renamed.html"
    And no redirect points at another redirect

  Scenario: A story that redirects to a story that is retired later still lands on the final story
    Given the story "old-article" is retired into "old-post"
    When the story "old-post" is retired into "merged"
    Then the site redirect store maps "/articles/old-article.html" to "/articles/merged.html"
    And the site redirect store maps "/notes/old-post.html" to "/articles/merged.html"

  Scenario Outline: A retirement the site cannot honour is refused and writes nothing
    When retiring "<story>" into "<target>" is attempted
    Then the retirement is refused saying "<reason>"
    And no record changed

    Examples:
      | story       | target      | reason                |
      | old-article | nowhere     | No story found        |
      | old-article | old-article | itself                |
      | old-article | draft-only  | not published         |
      | old-article | retired-one | retired and redirects |

  Scenario: Retiring a story that was never published is refused
    When retiring "draft-only" into "merged" is attempted
    Then the retirement is refused saying "never published"

  Scenario: The cross-story boilerplate check ignores a retired story
    Given the story "old-article" is retired into "merged"
    Then the cross-story boilerplate check does not compare "old-article"

  Scenario: A dry run lists what would change and writes nothing
    When the command "stories retire --story item-old-article --redirect-to item-merged --dry-run" is run
    Then the command printed a line containing "would unpublish"
    And the command printed a line containing "would redirect"
    And no record changed

  Scenario: Undo brings the story back and removes its redirects
    Given the story "old-article" is retired into "merged"
    When the retirement of "old-article" is undone
    Then the page "articles/old-article.html" is served again
    And the site redirect store has no redirect from "/articles/old-article.html"
    And the story "old-article" is in the published stage
    And a fresh projection of everything finds nothing to change

  Scenario: Retiring the same story again toward the same target changes nothing
    Given the story "old-article" is retired into "merged"
    Then retiring "old-article" into "merged" again plans no change
