@backend @reference-medium
Feature: A Reference's medium is read from its address by rule, kept in a sparse list, and shown on public pages as videos
  The newsroom classifies a Reference's medium separately from its evidence level and its voice. The medium is set from the address alone, by
  no model, and only where the address is certain: a video on YouTube, Vimeo, Dailymotion, Loom, Wistia, TED or Twitch has the medium "video",
  and any other address has none. A channel page, a user page, a Vimeo category or a youtube.com about page is not a video. A playlist, showcase,
  album or collection is an aggregation: it gets the evidence level "aggregation", the same field the decision model will write later, and it is
  never listed as a video. A YouTube watch address that carries a playlist is the video, and the playlist's own address is recorded separately for
  the story that will follow playlists later. Every way of creating a Reference sets these, and a sparse index lists the Reference by corpus, medium
  and vote, newest first, so a public page reads only the accepted videos without filtering anything out. A site shows its videos by placing a
  references include with the medium "video" on a page it already has; nothing appears until it does. Nothing here touches production: the backend
  is in memory.

  Scenario Outline: A video address on a known platform is a video
    When the medium of "<address>" is read
    Then its medium is "video"
    And its evidence level is empty
    Examples:
      | address                                                          |
      | https://www.youtube.com/watch?v=dQw4w9WgXcQ                      |
      | https://m.youtube.com/watch?v=dQw4w9WgXcQ                        |
      | https://youtu.be/dQw4w9WgXcQ?t=3                                 |
      | https://www.youtube.com/shorts/dQw4w9WgXcQ                       |
      | https://www.youtube.com/live/dQw4w9WgXcQ                         |
      | https://www.youtube.com/embed/dQw4w9WgXcQ                        |
      | https://vimeo.com/123456789                                      |
      | https://player.vimeo.com/video/123456789                         |
      | https://vimeo.com/channels/staffpicks/123456789                  |
      | https://www.dailymotion.com/video/x8abcde                        |
      | https://www.loom.com/share/0123456789abcdef0123456789abcdef      |
      | https://acme.wistia.com/medias/abcde12345                        |
      | https://www.ted.com/talks/ken_robinson_do_schools_kill_creativity |
      | https://www.twitch.tv/videos/123456789                           |

  Scenario Outline: An address that is not certainly one video has no medium
    A page about a video, a channel, a category or a profile is not the video, and an unknown site is never guessed from its path.
    When the medium of "<address>" is read
    Then it has no medium
    And its evidence level is empty
    Examples:
      | address                                              |
      | https://www.youtube.com/about/                       |
      | https://www.youtube.com/@somechannel                 |
      | https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv |
      | https://music.youtube.com/watch?v=dQw4w9WgXcQ        |
      | https://example.org/watch?v=dQw4w9WgXcQ              |
      | https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ |
      | https://vimeo.com/categories/animation               |
      | https://vimeo.com/staffpicks                         |
      | https://www.ted.com/talks                            |
      | https://www.twitch.tv/somechannel                    |
      | https://example.org/paper.pdf                        |

  Scenario Outline: A playlist, showcase or collection is an aggregation and is not a video
    When the medium of "<address>" is read
    Then it has no medium
    And its evidence level is "aggregation"
    Examples:
      | address                                                                   |
      | https://www.youtube.com/playlist?list=PLJkNSeYcYBlCaamscxip0l2LGYCZ2TIom   |
      | https://vimeo.com/showcase/7654321                                         |
      | https://www.dailymotion.com/playlist/x6abcd                                |
      | https://www.twitch.tv/collections/abcDEF123                                |

  Scenario: A watch address with a playlist is the video, and the playlist is recorded separately
    When the medium of "https://www.youtube.com/watch?v=JDAPDpbXRXw&list=PLJkNSeYcYBlCaamscxip0l2LGYCZ2TIom&ab_channel=ProbablyPrivate" is read
    Then its medium is "video"
    And its evidence level is empty
    And its playlist address is "https://www.youtube.com/playlist?list=PLJkNSeYcYBlCaamscxip0l2LGYCZ2TIom"

  Scenario Outline: Every way of creating a Reference records a video address as a video in the pending video list
    When a Reference is created through "<path>" at the address "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in the "alpha-site" corpus
    Then the Reference's medium list is "knowledge-corpus-alpha-site#video#pending"
    Examples:
      | path                                              |
      | papyrus references import (CLI)                   |
      | email submission                                  |
      | monitor delivery                                  |
      | named import (cursor:...)                         |
      | Slack / console chat Reference.create             |
      | console intake mutation (intakePendingReferences) |

  Scenario: A Reference created at an ordinary address has no medium field and no medium list
    When a Reference is created through "monitor delivery" at the address "https://example.org/an-article" in the "alpha-site" corpus
    Then the Reference names no medium field

  Scenario: A playlist address is created as an aggregation that no video list holds
    When a Reference is created through "papyrus references import (CLI)" at the address "https://www.youtube.com/playlist?list=PLJkNSeYcYBlCaamscxip0l2LGYCZ2TIom" in the "alpha-site" corpus
    Then the Reference's evidence level is "aggregation"
    And the Reference is in no medium list

  Scenario: A vote moves a video between the lists of its corpus, and an archived video leaves them all
    Given a pending video in the "alpha-site" corpus
    When the Reference is voted "accept"
    Then the Reference's medium list is "knowledge-corpus-alpha-site#video#accepted"
    When the Reference is voted "reject"
    Then the Reference's medium list is "knowledge-corpus-alpha-site#video#rejected"
    When the Reference is voted "archive"
    Then the Reference is in no medium list

  Scenario: Two corpora never share a medium list
    Given a pending video in the "alpha-site" corpus
    And a pending video in the "beta-site" corpus
    Then the two medium lists are "knowledge-corpus-alpha-site#video#pending" and "knowledge-corpus-beta-site#video#pending"

  Scenario: The backfill previews by default and writes only when asked
    Given a corpus of existing References with a video, a video with a playlist, a playlist and an article, none tagged yet
    When the medium backfill runs without the write flag
    Then the medium backfill wrote nothing
    And it reports 2 videos, 1 aggregation and 1 playlist address to record
    When the medium backfill runs with the write flag
    Then the video is tagged "video" and listed in "knowledge-corpus-demo#video#accepted"
    And both videos wait in the content-needed list "knowledge-corpus-demo#video#needs_content#accepted", because nothing is captured yet
    And the video with a playlist records "https://www.youtube.com/playlist?list=PLJkNSeYcYBlCaamscxip0l2LGYCZ2TIom"
    And the playlist has the evidence level "aggregation" and no medium
    And the article is not written
    And no vote or curation field was changed
    When the medium backfill runs with the write flag
    Then the medium backfill wrote nothing

  Scenario: A site shows its accepted videos on a page it adds, newest first, linking to the source
    Given a site whose videos page places a references include with the medium "video", and a corpus with accepted, pending and rejected videos, a playlist and an article
    When the home-page-snapshot task runs
    Then the videos page lists "Newest video", "Older video" and "Loom walkthrough" in that order
    And no video card repeats a "Video" label, because every card in the block is a video
    And every video card shows the video's own thumbnail from the site's storage, loads no picture from another host, and links out to its source
    And the videos page embeds nothing and loads no third-party script
    And the videos page does not list "Pending video", "Rejected video", "A playlist" or "An article"

  Scenario: A block that mixes media keeps the Video label on the video cards, and shows confidence only where no editor accepted
    Once an editor has accepted a Reference the Cyclotron's confidence no longer matters, so its card shows none; a Reference a Cyclotron accepted on its own keeps it.
    Given a site whose home page places one block of every accepted Reference, and a corpus with an editor-accepted video, a Cyclotron-accepted video and an editor-accepted article
    When the home-page-snapshot task runs
    Then the card for "Newest video" says "Video" next to a "video" icon and shows no confidence
    And the card for "Auto video" says "Video" next to a "video" icon and shows a confidence
    And the card for "An article" has no Video label and shows no confidence

  Scenario: An editor's stars order public cards but are never published on the videos page
    Given a site whose videos page places a references include with the medium "video", and a corpus with accepted, pending and rejected videos, a playlist and an article
    And an editor rated "Older video" 5 stars
    When the home-page-snapshot task runs
    Then no file the site wrote mentions a star field or who rated

  Scenario: A site that does not place the block shows no videos
    Given a site with a home page setting whose pages place no medium include, and a corpus with accepted videos
    When the home-page-snapshot task runs
    Then no page has a videos block

  Scenario: An unknown medium in an include fails the build naming the page
    Given a site whose videos page places a references include with the medium "podcast"
    Then the videos build failed saying "pages/videos.md" and "medium must be one of video"

  Scenario: A video accepted before the backfill still appears, because the public record reads the address when no medium is stored
    Given a site whose videos page places a references include with the medium "video", and a corpus whose accepted videos have no stored medium
    When the home-page-snapshot task runs
    Then the videos page lists "Newest video", "Older video" and "Loom walkthrough" in that order
