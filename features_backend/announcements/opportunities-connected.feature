Feature: A newsroom editor can search X with the publication's existing connection
  The search does not post and does not give a credential to the caller.
  An admin opts in with a separate budget; the server refuses unauthorized or over-budget searches before contacting X.

  Scenario: A person sees only public posts and can replay the capture
    Given a dedicated site has an existing connected X account and a search cap for one page
    When a signed-in editor requests opportunities
    Then only a public author's post and an estimated-cost receipt are returned
    And X receives one fixed GET search without a second page

  Scenario: Agents and users from another tenant cannot spend the site's search allowance
    Given a dedicated site has an existing connected X account and a search cap for one page
    When a CLI credential, a reader, an IAM role, and a foreign editor try to search
    Then the search is refused without reserving money or touching X

  Scenario: The stored cap cannot be exceeded by another search
    Given a dedicated site has an existing connected X account and a search cap for one page
    When a signed-in editor requests opportunities twice
    Then the second search is stopped before contacting X

  Scenario: An agent cannot turn on or reprice paid discovery
    Given a dedicated site has an existing connected X account and a search cap for one page
    When an admin's CLI credential tries to change the stored search settings
    Then the search allowance and price are unchanged
