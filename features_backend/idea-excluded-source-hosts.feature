Feature: A site can name source hosts its AI drafts never cite
  A site can list hosts that must never be cited in an AI draft, for example a competing publication. The list is explicit: Papyrus
  does not classify hosts as news or blog, so the site names each host. A host matches itself and every subdomain of it, and nothing
  that only shares part of its name. The site lists the hosts in the excludedSourceHosts setting of the knowledgeRun block of its site
  file. The scheduled run hands them to the trend drafts and the monitor stories as an exclude-host flag for each. A monitored item
  from an excluded host is never a candidate for a monitor story. A trend story is never shown an item from an excluded host and never
  cites one; the host's items still count in the statistics, because the statistics describe the topic and not the source. The
  citation check also rejects any sentence that cites an excluded item, so the rule holds even if the model were shown one. Separately,
  monitor stories leave alone any monitor that an enabled automation of the site already handles, so a site that turns monitor stories
  on does not get a second draft of what the automation drafts.

  Scenario: A monitored item from an excluded host is never drafted
    Given a site "example-site" with the sections "Analysis" and "Tools"
    And the monitors of the site delivered these excluded-host items:
      | monitor | title             | address                                | days ago |
      | hn      | A rival's take    | https://ipwatchdog.com/2026/10/take    | 1        |
      | hn      | An independent    | https://www.example2.org/post          | 2        |
    When the operator drafts monitor stories excluding the host "ipwatchdog.com"
    Then no monitor story was drafted from "A rival's take"
    And the monitor story run counted 1 item as excluded host

  Scenario: A subdomain of an excluded host is excluded and a host that only shares part of the name is not
    Given a site "example-site" with the sections "Analysis" and "Tools"
    And the monitors of the site delivered these excluded-host items:
      | monitor | title          | address                           | days ago |
      | hn      | On a subdomain | https://news.ipwatchdog.com/a     | 1        |
      | hn      | A lookalike    | https://notipwatchdog.com/example2.org/b | 2        |
    When the operator drafts monitor stories excluding the host "ipwatchdog.com"
    Then no monitor story was drafted from "On a subdomain"
    And the monitor story run counted 1 item as excluded host

  Scenario: A Reference an enabled automation has already written a story for is left alone, one it never ran for is drafted
    Given a site "example-site" with the sections "Analysis" and "Tools"
    And the monitors of the site delivered these excluded-host items:
      | monitor | title            | address                       | days ago |
      | ttab    | A board decision | https://www.example1.org/a    | 1        |
      | hn      | A tool           | https://www.example2.org/post | 2        |
    And an enabled automation is triggered by the monitor "ttab"
    And a story written by the automation is based on "A board decision"
    When the operator drafts monitor stories excluding no host
    Then no monitor story was drafted from "A board decision"
    And the monitor story run counted 1 item as handled by an automation

  Scenario: A Reference whose enabled automation never ran is drafted like any other
    Given a site "example-site" with the sections "Analysis" and "Tools"
    And the monitors of the site delivered these excluded-host items:
      | monitor | title            | address                       | days ago |
      | ttab    | A board decision | https://www.example1.org/a    | 1        |
    And an enabled automation is triggered by the monitor "ttab"
    When the operator drafts monitor stories excluding no host
    Then the monitor story run counted 0 item as handled by an automation
    And a monitor story was drafted from "A board decision"

  Scenario: A trend story is never shown an item from an excluded host, but the statistics still count it
    Given a trend snapshot whose releases are published on "site.example"
    When the trends are built excluding the host "site.example"
    Then the model is shown no items
    And the signal for "Zed" still reports its window count from the snapshot

  Scenario: The citation check rejects a sentence that cites an excluded item
    Given a trend snapshot whose releases are published on "site.example"
    When a draft citing those releases is checked excluding the host "site.example"
    Then the draft fails the citation check because it cites an excluded source host

  Scenario: The scheduled run hands the site's excluded hosts to both draft steps
    Given the scheduled run excludes the hosts "ipwatchdog.com,other.example"
    When the trend-drafts and monitor-stories steps build their commands
    Then both commands carry an exclude-host flag for "ipwatchdog.com" and for "other.example"
