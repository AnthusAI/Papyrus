Feature: Links are explored through trackers, and a search finds the page when the link will not
  A newsletter link is usually a subscriber-specific tracker wrapper (SendGrid, Beehiiv, Mailchimp and the like) that redirects to the
  real article. Resolving it is the cost of doing research, so Papyrus follows it: HTTP redirects, meta refresh, simple script
  redirects, and the destination that a known wrapper carries in its own address. Only public http and https pages are fetched, every
  hop is checked again, and the work is bounded only by real constraints (a redirect loop, a size guard, timeouts and one overall
  deadline), never by a hop count. The result is the canonical destination: tracking parameters are stripped, and the wrapper address
  appears nowhere in it. When the address cannot be followed or read, Papyrus searches the web for the headline (or the summary, or the
  link text), picks the result whose title, snippet and domain best match, and marks it found via search with the query and the match
  score, so an editor knows it is not the original address. Search uses Tavily; without a key the search is skipped and the reason is
  search_unavailable. Every failure has one typed reason that names no address. Email intake, monitor stories and reference intake all
  use this one exploration.

  Scenario: A tracker chain is followed to the article and its text is read
    Given a newsletter link that redirects through "links.publisher.example" to the article "https://www.publisher.example/news/licensing"
    When the link is explored with the headline "Regulators approve cross-border licensing scheme for open models"
    Then the exploration found the destination "https://www.publisher.example/news/licensing" directly
    And the exploration read the article text
    And the exploration result does not contain the newsletter link

  Scenario: Tracking parameters are stripped from the destination
    Given a newsletter link that redirects to the article "https://www.publisher.example/news/licensing?utm_source=newsletter&mc_cid=77&fbclid=9&page=2#top"
    When the link is explored with the headline "Regulators approve cross-border licensing scheme for open models"
    Then the exploration found the destination "https://www.publisher.example/news/licensing?page=2" directly

  Scenario: A link that is gone falls back to a search by headline and is marked found via search
    Given a newsletter link that answers 404
    And a search for the headline finds the article "https://www.publisher.example/news/licensing"
    When the link is explored with the headline "Regulators approve cross-border licensing scheme for open models"
    Then the exploration found the destination "https://www.publisher.example/news/licensing" via search
    And the exploration recorded the search query "Regulators approve cross-border licensing scheme for open models" and a match score of at least 0.9
    And the exploration recorded that the original link failed with "http_4xx"
    And the exploration result does not contain the newsletter link

  Scenario: Without a search key the fallback is search_unavailable
    Given a newsletter link that answers 404
    And no search key is configured
    When the link is explored with the headline "Regulators approve cross-border licensing scheme for open models"
    Then the exploration failed with "search_unavailable"
    And the exploration recorded that the original link failed with "http_4xx"

  Scenario: A search that finds nothing like the headline is no_match
    Given a newsletter link that answers 404
    And a search for the headline finds only the unrelated article "https://news.example/weather" titled "Weather outlook for the weekend"
    When the link is explored with the headline "Regulators approve cross-border licensing scheme for open models"
    Then the exploration failed with "no_match"

  Scenario Outline: A private address is refused and nothing is fetched
    Given the address "<address>"
    When the address is explored without search
    Then the exploration failed with "not_public"
    And no page was requested

    Examples:
      | address                                    |
      | http://10.0.0.5/admin                      |
      | http://169.254.169.254/latest/meta-data/   |
      | http://localhost:8080/                     |
      | https://user:secret@publisher.example/a    |

  Scenario: A redirect that leads to a private address is refused at that hop
    Given a newsletter link that redirects to "http://192.168.1.1/router"
    When the link is explored without search
    Then the exploration failed with "not_public"

  Scenario: A redirect loop is detected
    Given a newsletter link that redirects in a loop
    When the link is explored without search
    Then the exploration failed with "loop"

  Scenario Outline: Every failure has a typed reason that names no address
    Given a newsletter link that fails with <failure>
    When the link is explored without search
    Then the exploration failed with "<reason>"
    And the failure reason names no address

    Examples:
      | failure                          | reason     |
      | a missing host name              | dns        |
      | a timeout                        | timeout    |
      | a refused connection             | connection |
      | a certificate error              | tls        |
      | status 404                       | http_4xx   |
      | status 503                       | http_5xx   |
      | status 403                       | blocked    |
      | status 429                       | blocked    |
      | an image instead of a page       | unreadable |
      | a redirect with no target        | unreadable |

  Scenario: A newsletter wrapper is resolved for an editor and stays private
    Given an email receipt with the newsletter link "https://link.mail.beehiiv.com/ss/c/private-recipient" titled "Regulators approve cross-border licensing scheme for open models"
    And the wrapper redirects to the article "https://news.example.org/story?utm_source=beehiiv"
    When an editor resolves the candidate
    Then the editor sees the destination "https://news.example.org/story" and no search mark
    And the recorded resolution holds the destination and not the newsletter link

  Scenario: A dead wrapper is resolved by headline search and the editor sees it was found via search
    Given an email receipt with the newsletter link "https://link.mail.beehiiv.com/ss/c/private-recipient" titled "Regulators approve cross-border licensing scheme for open models"
    And the wrapper answers 404
    And a search for the headline finds the article "https://news.example.org/story"
    When an editor resolves the candidate
    Then the editor sees the destination "https://news.example.org/story" marked found via search with the query and match score
    And the recorded resolution holds the destination and not the newsletter link
