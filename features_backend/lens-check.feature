Feature: papyrus stories lens-check reports what code can check about a Story for the four audiences
  An agent about to hand a Story to a person runs papyrus stories lens-check first, fixes what it can and records what it found. The
  command reads one Story's current version and, when it is given the site's web directory, the site's settings. It reads nothing else
  from the site, writes nothing, calls no model and shows no number Papyrus made up. Every check ends in one of five states: it looks
  fine, it needs a look, it is a problem, it could not be checked or it does not apply. Each finding is one plain sentence with the
  evidence behind it. Four problems must be fixed before a lens step can close as done, and the command says so clearly: an image with
  no alt text, a third-party image with no credit, a video with no title or no credit, and a Markdown copy that differs from the Story's source. A check that could not be
  made is never a pass: it says what Papyrus could not tell and why. The preview the checks judge is built by the same function the
  projector uses for the page's head, so a check never judges a stand-in.

  Scenario: An image with no alt text is a problem that blocks the step
    Given a Story with this body
      """
      ::image{src="assets/harbour.jpg"}

      The harbour.
      """
    When the lens checks run
    Then the finding "P7" is a "problem"
    And the finding "A10" is a "concern"
    And the finding "P7" says "line 1"
    And "P7" is among the problems that block a lens step

  Scenario: An empty alt text is accepted as a deliberate decoration
    Given a Story with this body
      """
      ::image{src="assets/rule.png" alt=""}

      The harbour.
      """
    When the lens checks run
    Then the finding "P7" is a "pass"
    And the finding "P7" says "marked as decoration"

  Scenario: A Story with no images has nothing to check about alt text or credit
    Given a Story with this body
      """
      The harbour.
      """
    When the lens checks run
    Then the finding "P7" is a "not_applicable"
    And the finding "P10" is a "not_applicable"
    And the finding "C6" is a "not_applicable"

  Scenario: Alt text that is a filename, a generic word or a copy of the caption needs a look
    Given a Story with this body
      """
      ::image{src="assets/harbour.jpg" alt="harbour.jpg"}

      ::image{src="assets/dock.jpg" alt="image"}

      ::image{src="assets/crane.jpg" alt="A crane" caption="A crane"}
      """
    When the lens checks run
    Then the finding "P8" is a "concern"
    And the finding "P8" says "a filename or a generic word"
    And the finding "P8" says "a copy of the caption"

  Scenario: A stock cover picture with no credit is a problem in two lenses
    Given a Story with the front matter
      """
      title: Board refuses
      image: /assets/harbour/harbour.jpg
      coverImage:
        source: wikimedia-commons
        srcPath: assets/harbour/harbour.jpg
        creator: Ana Example
      """
    And the Story body
      """
      ::image{src="/assets/harbour/harbour.jpg" alt="A harbour"}

      The harbour.
      """
    When the lens checks run
    Then the finding "P10" is a "problem"
    And the finding "C6" is a "problem"
    And "P10" is among the problems that block a lens step
    And "C6" is among the problems that block a lens step

  Scenario: A credited third-party picture passes
    Given a Story with the front matter
      """
      title: Board refuses
      image: /assets/harbour/harbour.jpg
      coverImage:
        source: wikimedia-commons
        srcPath: assets/harbour/harbour.jpg
      """
    And the Story body
      """
      ::image{src="/assets/harbour/harbour.jpg" alt="A harbour" credit="Image: Ana Example, CC BY 4.0, via Wikimedia Commons"}

      The harbour.
      """
    When the lens checks run
    Then the finding "P10" is a "pass"
    And no lens step is blocked

  Scenario: A picture at a web address with no credit is third-party by nature
    Given a Story with this body
      """
      ::image{src="https://photos.example.test/x.jpg" alt="A harbour"}
      """
    When the lens checks run
    Then the finding "P10" is a "problem"

  Scenario: A local picture with no record of where it came from could not be checked
    Given a Story with this body
      """
      ::image{src="assets/chart.png" alt="A chart of costs"}
      """
    When the lens checks run
    Then the finding "P10" is a "not_assessable"
    And the finding "P10" says "Papyrus cannot tell where this picture came from"
    And no lens step is blocked

  Scenario: The Markdown copy is the Story's source
    Given a Story with this body
      """
      ## Findings

      The board refused the merger.
      """
    When the lens checks run
    Then the finding "A2" is a "pass"

  Scenario: A Markdown copy that differs from the source is a problem that blocks the step
    Given a Story with this body
      """
      The board refused the merger.

      A second paragraph the copy loses.
      """
    And the Markdown copy is built with a fault that loses the last paragraph
    When the lens checks run
    Then the finding "A2" is a "problem"
    And the finding "A2" says "differs from the Story's source"
    And "A2" is among the problems that block a lens step

  Scenario: Blocks the Markdown copy leaves out by design are reported once as a warning, not as a difference
    Given a Story with this body
      """
      The board refused the merger.

      ::include{kind="listing" section="news"}
      """
    When the lens checks run
    Then the finding "A2" is a "pass"
    And the finding "A3" is a "concern"
    And the finding "A3" says "include at line 3"

  Scenario: An island with a summary is kept and one without is reported
    Given a Story with this body
      """
      ::island{name="chart" summary="Costs fell."}

      ::island{name="widget"}
      """
    When the lens checks run
    Then the finding "A3" is a "concern"
    And the finding "A3" says "island without a summary at line 3"
    And the finding "A3" does not say "line 1"

  Scenario: A site that publishes no Markdown copies makes the copy checks not apply
    Given the site publishes no Markdown copies
    And a Story with this body
      """
      The board refused the merger.
      """
    When the lens checks run
    Then the finding "A1" is a "not_applicable"
    And the finding "A2" is a "not_applicable"
    And the finding "A2" says "This site does not publish Markdown copies"

  Scenario: A Story marked noindex gets no Markdown copy
    Given the site is live with a public address
    And a Story with the front matter
      """
      title: Board refuses
      noindex: true
      """
    And the Story body
      """
      The board refused the merger.
      """
    When the lens checks run
    Then the finding "A1" is a "concern"
    And the finding "S4" is a "concern"
    And the finding "S7" is a "concern"

  Scenario: The Markdown copy needs a title, summary, byline, date and canonical address
    Given the site is live with a public address
    And a Story with this body
      """
      The board refused the merger.
      """
    When the lens checks run
    Then the finding "A4" is a "concern"
    And the finding "A4" says "no summary"
    And the finding "A4" says "no byline"

  Scenario: Citations must resolve and be listed, and claims with names, numbers or quotations must cite
    Given a Story with the front matter
      """
      title: Board refuses
      citations:
        minutes:
          type: webpage
          title: Minutes
      """
    And the Story body
      """
      The board voted 5 to 2 on March 3, said Dana Reyes [@minutes] [@missing].

      The Acme Corporation stated 40 percent.
      """
    When the lens checks run
    Then the finding "A5" is a "concern"
    And the finding "A5" says "missing"
    And the finding "A5" says "no ::citations{} line"
    And the finding "A5" says "cites nothing"

  Scenario: Weak link text and pictures of tables are reported as information
    Given a Story with this body
      """
      Read the minutes [here](https://example.test/minutes).

      ::image{src="assets/budget-table.png" alt="The budget table"}
      """
    When the lens checks run
    Then the finding "A8" is a "concern"
    And the finding "A11" is a "concern"
    And "A8" has the default severity "info"

  Scenario: Headings that skip a level or say nothing need a look in two lenses
    Given a Story with this body
      """
      # Board refuses

      #### Details

      ## Introduction
      """
    When the lens checks run
    Then the finding "P6" is a "concern"
    And the finding "A9" is a "concern"
    And the finding "P6" says "skips from level 1 to level 4"
    And the finding "P6" says "says nothing about the section"

  Scenario: A Story with no dek says the page will use its first paragraph
    Given a Story with this body
      """
      The board refused the merger.
      """
    When the lens checks run
    Then the finding "P2" is a "concern"
    And the finding "P2" says "first paragraph"
    And the finding "S2" is a "pass"
    And the finding "S2" says "the first paragraph"

  Scenario: A Story with no dek and no usable first paragraph shares the whole site's description
    Given the site has a description "Example news."
    And a Story with this body
      """
      ::image{src="assets/a.jpg" alt="A"}
      """
    When the lens checks run
    Then the finding "S2" is a "concern"
    And the finding "C2" is a "concern"
    And the finding "S2" says "site-wide description"

  Scenario: A placeholder headline needs a look and the duplicate-title comparison is said not to be done
    Given a Story titled "Untitled draft"
    When the lens checks run
    Then the finding "P1" is a "concern"
    And the finding "P1" says "placeholder"
    And the finding "S1" lists "whether another Story on this site has the same title" as not checked

  Scenario: The share picture comes from the Story, its first picture or the site default
    Given a Story with the front matter
      """
      title: Board refuses
      image: /assets/own.jpg
      """
    When the lens checks run
    Then the finding "C3" says "its own picture"
    Given a Story with this body
      """
      ::image{src="assets/inline.jpg" alt="A harbour"}
      """
    When the lens checks run
    Then the finding "C3" says "first picture"
    Given a Story with this body
      """
      Words only.
      """
    And the site has a default share picture
    When the lens checks run
    Then the finding "C3" says "no picture of its own"

  Scenario: A share picture needs its own description
    Given a Story with the front matter
      """
      title: Board refuses
      image: /assets/own.jpg
      """
    When the lens checks run
    Then the finding "C5" is a "concern"
    And the finding "C5" says "imageAlt"
    Given a Story with the front matter
      """
      title: Board refuses
      image: /assets/own.jpg
      imageAlt: A harbour at dusk
      """
    When the lens checks run
    Then the finding "C5" is a "pass"

  Scenario: A number or name in the share text that the Story does not contain needs a look
    Given a Story with the front matter
      """
      title: Board refuses 99 mergers
      summary: Dana Reyes led the vote.
      """
    And the Story body
      """
      The board refused the merger.
      """
    When the lens checks run
    Then the finding "C7" is a "concern"
    And the finding "C7" says "99"

  Scenario: Without the site's settings the checks that need them say so
    Given a Story with this body
      """
      The board refused the merger.
      """
    When the lens checks run
    Then the finding "A1" is a "not_assessable"
    And the finding "S5" is a "not_assessable"
    And the finding "S6" is a "not_assessable"
    And the finding "C1" is a "not_assessable"
    And the finding "A13" is a "not_assessable"
    And the finding "S5" says "cannot read this site's settings"

  Scenario: A site with no public address cannot have its web addresses built
    Given the site has no public address
    And a Story with this body
      """
      The board refused the merger.
      """
    When the lens checks run
    Then the finding "S5" is a "not_assessable"
    And the finding "S5" says "no public address"
    And the finding "C1" is a "not_assessable"
    And the finding "S6" is a "not_assessable"

  Scenario: A site that is not live yet cannot be assessed for readers
    Given the site is not live yet
    And a Story with this body
      """
      The board refused the merger.
      """
    When the lens checks run
    Then the finding "A13" is a "not_assessable"
    And the finding "A13" says "not open to search or to AI readers yet"

  Scenario: A live site with a complete Story has its address, structured data and sitemap entry checked
    Given the site is live with a public address
    And a Story with the front matter
      """
      title: Board refuses
      summary: The board refused the merger on March 3.
      date: 2026-03-03
      author: Dana Reyes
      image: /assets/own.jpg
      imageAlt: A harbour at dusk
      """
    And the Story body
      """
      The board refused the merger on March 3.
      """
    When the lens checks run
    Then the finding "A13" is a "pass"
    And the finding "S5" is a "pass"
    And the finding "S5" says "https://example.test/"
    And the finding "S6" is a "pass"
    And the finding "S7" is a "pass"
    And the finding "C1" is a "pass"
    And the finding "A4" is a "pass"

  Scenario: Structured data with no author or date is reported
    Given the site is live with a public address
    And a Story with the front matter
      """
      title: Board refuses
      summary: The board refused the merger.
      image: /assets/own.jpg
      """
    And the Story body
      """
      The board refused the merger.
      """
    When the lens checks run
    Then the finding "S6" is a "concern"
    And the finding "S6" says "datePublished"
    And the finding "S6" says "author"

  Scenario: Every finding names its lens, its method and its evidence, and checks that report the same fact appear in each lens
    Given a Story with this body
      """
      ::image{src="assets/a.jpg"}
      """
    When the lens checks run
    Then every finding has a step, a check, a state, a method and a message
    And the finding "P7" is shown in the lens "review_people"
    And the finding "A10" is shown in the lens "review_reader_agents"
    And the finding "P6" and the finding "A9" are the same fact shown in two lenses

  Scenario: The lens filter keeps one lens
    Given a Story with this body
      """
      ::image{src="assets/a.jpg"}
      """
    When the lens checks run for the lens "social"
    Then every finding is in the lens "review_social"

  Scenario: Checks that need a model, the rest of the site or a person are listed as not run
    When the lens checks are listed as not run
    Then "P3" is listed as not run because "needs the decision model"
    And "S8" is listed as not run because "needs the rest of the site"
    And "P14" is listed as not run because "a person decides"
    And no check that is run is also listed as not run

  Scenario: The command prints each finding in plain words and writes nothing
    Given a Story at the "copywriting" stage with this body
      """
      ::image{src="assets/harbour.jpg"}

      The harbour.
      """
    When I run "stories lens-check" with "--story story-1"
    Then the lens-check output has a finding line for "P7" that starts with the word "Problem"
    And the lens-check output has a summary line for each of the four lenses
    And the lens-check output has a "blocked" line for "P7"
    And the lens-check output says how many checks were not run
    And the lens-check command wrote no records

  Scenario: The command can limit itself to one lens and print JSON
    Given a Story at the "copywriting" stage with this body
      """
      ::image{src="assets/harbour.jpg"}
      """
    When I run "stories lens-check" with "--story story-1 --lens search --json"
    Then the JSON findings are all in the lens "review_search"
    And the JSON result lists the checks that were not run
    And the JSON result says the site settings were not read

  Scenario: The command refuses an unknown lens
    Given a Story at the "copywriting" stage with this body
      """
      Words.
      """
    When I run "stories lens-check" with "--story story-1 --lens seo"
    Then the lens-check command failed saying "Unknown lens"

  Scenario: The command reads the site's settings from a web directory
    Given a web directory whose projection.json describes a live site at "https://example.test"
    And a Story at the "copywriting" stage with this body
      """
      Words.
      """
    When I run "stories lens-check" with "--story story-1 --static" and that web directory
    Then the lens-check output reads "Looks fine" for "A13"

  Scenario: The command reads one Story and nothing else from the site
    Given a Story at the "copywriting" stage with this body
      """
      Words.
      """
    When I run "stories lens-check" with "--story story-1"
    Then the command read only the Story's own versions

  # The share picture (check C4). A built address is not proof of a file: the check fetches the picture it would name in og:image, reads what came
  # back, and says what it saw. It never claims what a platform will do; WebP and AVIF are a compatibility risk, not a proven failure.
  Scenario Outline: The share picture is fetched and judged by what came back
    Given the site is live with a public address
    And a Story with the front matter
      """
      title: Board refuses
      summary: The board refused the merger on March 3.
      date: 2026-03-03
      author: Dana Reyes
      image: /assets/share.img
      imageAlt: A harbour at dusk
      """
    And the Story body
      """
      The board refused the merger.
      """
    And the share picture answers with status <status>, type "<type>" and a <format> of <width> by <height> pixels
    When the lens checks run
    Then the finding "C4" is a "<state>"
    And the finding "C4" says "<words>"

    Examples:
      | status | type       | format | width | height | state   | words                                  |
      | 200    | image/jpeg | jpeg   | 1200  | 630    | pass    | https://example.test/assets/share.img  |
      | 200    | image/png  | png    | 1200  | 630    | pass    | 1200x630                               |
      | 200    | image/webp | webp   | 912   | 572    | concern | JPEG or PNG                            |
      | 200    | image/jpeg | jpeg   | 300   | 157    | concern | smaller                                |
      | 200    | image/jpeg | png    | 1200  | 630    | concern | does not match                         |
      | 404    | image/jpeg | jpeg   | 1200  | 630    | concern | status 404                             |

  Scenario: A share picture that cannot be requested is not verified, not passed
    Given the site is live with a public address
    And a Story with the front matter
      """
      title: Board refuses
      image: /assets/share.jpg
      """
    And the Story body
      """
      The board refused the merger.
      """
    And the share picture cannot be requested
    When the lens checks run
    Then the finding "C1" is a "pass"
    And the finding "C4" is a "not_assessable"
    And the finding "C4" says "not verified"

  Scenario: Without a fetch the picture is not verified even though its address can be built
    Given the site is live with a public address
    And a Story with the front matter
      """
      title: Board refuses
      image: /assets/share.jpg
      """
    And the Story body
      """
      The board refused the merger.
      """
    When the lens checks run
    Then the finding "C1" is a "pass"
    And the finding "C4" is a "not_assessable"

  Scenario: A Story with no picture and a site with no default is flagged
    Given the site is live with a public address
    And a Story with this body
      """
      The board refused the merger.
      """
    And the share picture answers with status 200, type "image/jpeg" and a jpeg of 1200 by 630 pixels
    When the lens checks run
    Then the finding "C4" is a "concern"
    And the finding "C4" says "no picture"

  Scenario: A picture that is not at an absolute HTTPS address is flagged
    Given the site is live with a public address
    And a Story with the front matter
      """
      title: Board refuses
      image: http://cdn.example.test/share.jpg
      """
    And the Story body
      """
      The board refused the merger.
      """
    And the share picture answers with status 200, type "image/jpeg" and a jpeg of 1200 by 630 pixels
    When the lens checks run
    Then the finding "C4" is a "concern"
    And the finding "C4" says "absolute HTTPS"

  Scenario: The finding carries the line for the social review note
    Given the site is live with a public address
    And a Story with the front matter
      """
      title: Board refuses
      image: /assets/share.webp
      """
    And the Story body
      """
      The board refused the merger.
      """
    And the share picture answers with status 200, type "image/webp" and a webp of 912 by 572 pixels
    When the lens checks run
    Then the finding "C4" says "Record this in the social review note: Share picture https://example.test/assets/share.webp"
    And the finding "C4" says "912x572"

  Scenario: A dek that differs from the blurb is expected and raises nothing
    Given a Story with the front matter
      """
      title: Board refuses the merger
      dek: Directors said the price undervalued the company.
      blurb: Acme Corp's board refused Beta Ltd's merger offer on Tuesday, saying the price undervalued the company.
      """
    And the Story body
      """
      The board refused the merger.
      """
    When the lens checks run
    Then the finding "P2" is a "pass"

  Scenario: A dek that is a verbatim copy of the blurb is a concern
    Given a Story with the front matter
      """
      title: Board refuses the merger
      dek: The board refused the merger on Tuesday.
      blurb: The board refused the merger on Tuesday.
      """
    And the Story body
      """
      The board refused the merger.
      """
    When the lens checks run
    Then the finding "P2" is a "concern"
    And the finding "P2" says "copy of the blurb"
