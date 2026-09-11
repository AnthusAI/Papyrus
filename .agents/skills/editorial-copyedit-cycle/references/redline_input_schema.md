# redline_input.json schema

Input to `scripts/build_redline.py`. Assemble this from the draft, the
diagnose output, and the decisions you made in Step 3/5 of the skill.

```json
{
  "title": "Editorial Redline",
  "eyebrow": "papyrus editorial diagnose · copy-edit cycle",
  "subtitle": "“Article title” · STORY-ID · profile: publications/<pub>/style-profile.yml",
  "stats": {
    "scanned": 12,
    "rewritten": 3,
    "keptAsIs": 9,
    "extra": "2265 words · 150 sentences"
  },
  "draft_path": "/absolute/path/to/article.md",
  "note_html": "Optional free-text editor's note, as raw HTML (already escaped). Use <b>, <em>, <br>, <span class=\"card-id\">finding-...</span>. Omit or empty string to skip the note block entirely.",
  "rewrites": [
    {
      "findingId": "finding-...",
      "span": {"start": 0, "end": 0},
      "replacement": "The replacement text that goes in the article body.",
      "reasonAttr": "Short reason shown as a data attribute / tooltip on the inline edit.",
      "cardReason": "Longer explanation shown in the findings apparatus card below the article."
    }
  ],
  "skipGroups": [
    {
      "label": "Deliberate bookend",
      "findingIds": ["finding-...", "finding-..."],
      "quote": "The quoted excerpt(s) this group covers.",
      "reason": "Why these were skipped."
    }
  ],
  "rescan": {
    "rows": [
      ["Repetition findings", "5 groups / 10 spans", "4 groups / 8 spans"],
      ["Voice-mismatch findings", "3", "2"],
      ["Word count", "2,265", "2,244"],
      ["Lexical density", "0.623", "0.627"],
      ["Gzip ratio", "0.4209", "0.4214"]
    ],
    "footnote": "No new findings appeared anywhere else in the piece."
  },
  "footer": "papyrus editorial diagnose · decisions: 9 skip / 3 rewrite · options generated with <model>"
}
```

Notes:

- `rewrites[].span` must match byte offsets in the **original** draft text
  (the same `start`/`end` the diagnose finding reported) — the script applies
  all rewrites against the original draft in one pass, from the end of the
  file backward, so offsets don't shift mid-application.
- `stats`, `rescan`, and `note_html` are all optional — omit any of them and
  the script skips that section of the page.
- `skipGroups` is for presentation only (grouping related skip decisions with
  a shared quote/reason in the apparatus) — it doesn't need to cover every
  skipped finding one-to-one if several share the same reasoning.
- The draft is parsed as Markdown with a deliberately small feature set:
  `#`/`##`/`###` headings, blank-line-separated paragraphs, `[text](url)`
  links, and ` ```mermaid ` fenced code blocks (rendered natively by the
  Artifact tool — no library needed). Anything fancier in the source Markdown
  (tables, nested lists, etc.) will pass through as a literal paragraph rather
  than being specially formatted — check the output if the draft uses those.
