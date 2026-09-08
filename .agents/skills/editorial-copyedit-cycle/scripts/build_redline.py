#!/usr/bin/env python3
"""Build a before/after editorial redline page from a redline_input.json.

Usage:
    python3 build_redline.py redline_input.json output.html

See ../references/redline_input_schema.md for the input schema. The output
is a self-contained HTML fragment meant to be published with the Artifact
tool (it deliberately has no <html>/<head>/<body> wrapper — the Artifact tool
adds that).
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def inline_markdown(text: str) -> str:
    return LINK_RE.sub(
        lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener">{m.group(1)}</a>',
        text,
    )


def apply_rewrites(draft_text: str, rewrites: list[dict]) -> str:
    text = draft_text
    for r in sorted(rewrites, key=lambda r: -r["span"]["start"]):
        start, end = r["span"]["start"], r["span"]["end"]
        old = text[start:end]
        reason_attr = html.escape(r.get("reasonAttr", ""), quote=True)
        marker = (
            f"<span class='edit' data-finding=\"{r['findingId']}\" data-reason=\"{reason_attr}\">"
            f"<del>{old}</del><ins>{r['replacement']}</ins></span>"
        )
        text = text[:start] + marker + text[end:]
    return text


def markdown_to_html(text: str) -> str:
    blocks = text.split("\n\n")
    parts: list[str] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.startswith("```mermaid"):
            code_lines = [b[len("```mermaid"):].lstrip("\n")]
            while not code_lines[-1].rstrip().endswith("```") and "```" not in code_lines[-1]:
                i += 1
                code_lines.append(blocks[i])
            full = "\n\n".join(code_lines).replace("```", "").strip("\n")
            parts.append(f'<pre class="mermaid">\n{full}\n</pre>')
        elif b.startswith("### "):
            parts.append(f"<h3>{inline_markdown(b[4:])}</h3>")
        elif b.startswith("## "):
            parts.append(f"<h2>{inline_markdown(b[3:])}</h2>")
        elif b.startswith("# "):
            parts.append(f'<h1 class="doc-title">{inline_markdown(b[2:])}</h1>')
        elif b.strip():
            parts.append(f"<p>{inline_markdown(b)}</p>")
        i += 1
    return "\n".join(parts)


def render_stats(stats: dict | None) -> str:
    if not stats:
        return ""
    items = []
    if "scanned" in stats:
        items.append(f'<div class="stat"><b>{stats["scanned"]}</b> findings scanned</div>')
    if "rewritten" in stats:
        items.append(f'<div class="stat add"><b>{stats["rewritten"]}</b> rewritten</div>')
    if "keptAsIs" in stats:
        items.append(f'<div class="stat"><b>{stats["keptAsIs"]}</b> kept as-is</div>')
    if stats.get("extra"):
        items.append(f'<div class="stat">{html.escape(stats["extra"])}</div>')
    return '<div class="stats">\n' + "\n".join(items) + "\n</div>"


def render_note(note_html: str | None) -> str:
    if not note_html:
        return ""
    return f'<div class="editors-note">\n{note_html}\n</div>'


def render_apparatus(rewrites: list[dict], skip_groups: list[dict]) -> str:
    out = [
        '<div class="apparatus">',
        '  <h2 class="apparatus-head">Findings apparatus</h2>',
        '  <p class="apparatus-sub">Every finding from the diagnose scan, with the steering decision and rationale.</p>',
    ]
    if rewrites:
        out.append(f'  <div class="group-label rewrite">Rewritten <span class="n">{len(rewrites)}</span></div>')
        for r in rewrites:
            out.append('  <div class="card">')
            out.append(
                f'    <div class="card-top"><span class="card-id">{r["findingId"]}</span>'
                '<span class="card-kind rewrite">rewrite</span></div>'
            )
            original = r.get("originalExcerpt", "")
            out.append(
                f'    <div class="card-diff"><del>{original}</del><br><ins>{r["replacement"]}</ins></div>'
            )
            out.append(f'    <p class="card-reason">{r.get("cardReason", "")}</p>')
            out.append("  </div>")
    for group in skip_groups:
        ids = " + ".join(f'<span class="card-id">{fid}</span>' for fid in group["findingIds"])
        out.append(
            f'  <div class="group-label skip">{html.escape(group["label"])} &middot; kept '
            f'<span class="n">{len(group["findingIds"])}</span></div>'
        )
        out.append('  <div class="card">')
        out.append(f'    <div class="card-top">{ids}<span class="card-kind skip">skip</span></div>')
        if group.get("quote"):
            out.append(f'    <p class="card-quote">{group["quote"]}</p>')
        out.append(f'    <p class="card-reason">{group["reason"]}</p>')
        out.append("  </div>")
    out.append("</div>")
    return "\n".join(out)


def render_rescan(rescan: dict | None) -> str:
    if not rescan or not rescan.get("rows"):
        return ""
    rows_html = "\n".join(
        f"        <tr><td>{html.escape(str(row[0]))}</td><td>{html.escape(str(row[1]))}</td>"
        f"<td>{html.escape(str(row[2]))}</td></tr>"
        for row in rescan["rows"]
    )
    footnote = rescan.get("footnote", "")
    footnote_html = (
        f'\n    <p class="apparatus-sub" style="margin-top:14px;margin-bottom:0;">{html.escape(footnote)}</p>'
        if footnote
        else ""
    )
    return f"""  <div class="rescan">
    <h2 class="apparatus-head" style="font-size:18px;margin-bottom:4px;">Re-scanned after edit</h2>
    <p class="apparatus-sub" style="margin-bottom:16px;">Running <span class="card-id">editorial diagnose</span> again on the edited copy, to check the edit actually helped rather than just moved words around.</p>
    <table class="rescan-table">
      <thead><tr><th></th><th>Before</th><th>After</th></tr></thead>
      <tbody>
{rows_html}
      </tbody>
    </table>{footnote_html}
  </div>"""


PAGE_TEMPLATE = """<title>{title}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,500;8..60,600&family=Libre+Franklin:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{{
  --paper:#f2f1ea; --paper-raised:#fbfaf5; --ink:#1d1f1a; --ink-dim:#5c6058; --ink-faint:#8a8d83;
  --rule:#d9d7c9; --rule-strong:#c3c1b0;
  --accent-cut:#a3392b; --accent-cut-bg:#a3392b14;
  --accent-add:#2a6a55; --accent-add-bg:#2a6a5514;
  --accent-skip:#8a6a1e; --accent-skip-bg:#8a6a1e12;
  --link:#2a5a6a;
  --shadow:0 1px 2px rgba(30,30,20,.06),0 4px 16px rgba(30,30,20,.05);
  --serif:"Source Serif 4",Georgia,"Iowan Old Style",serif;
  --sans:"Libre Franklin",-apple-system,"Segoe UI",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,"SF Mono",monospace;
}}
@media (prefers-color-scheme: dark){{
  :root:not([data-theme="light"]){{
    --paper:#17181a; --paper-raised:#1e2022; --ink:#e8e7dd; --ink-dim:#a3a599; --ink-faint:#787a70;
    --rule:#33352e; --rule-strong:#454739;
    --accent-cut:#e17a68; --accent-cut-bg:#e17a6820;
    --accent-add:#6ec3a5; --accent-add-bg:#6ec3a520;
    --accent-skip:#dcb35a; --accent-skip-bg:#dcb35a1c;
    --link:#7fbccf;
    --shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.35);
  }}
}}
:root[data-theme="dark"]{{
  --paper:#17181a; --paper-raised:#1e2022; --ink:#e8e7dd; --ink-dim:#a3a599; --ink-faint:#787a70;
  --rule:#33352e; --rule-strong:#454739;
  --accent-cut:#e17a68; --accent-cut-bg:#e17a6820;
  --accent-add:#6ec3a5; --accent-add-bg:#6ec3a520;
  --accent-skip:#dcb35a; --accent-skip-bg:#dcb35a1c;
  --link:#7fbccf;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.35);
}}
*{{box-sizing:border-box;}}
body{{background:var(--paper);color:var(--ink);font-family:var(--serif);line-height:1.65;-webkit-font-smoothing:antialiased;}}
::selection{{background:var(--accent-add-bg);}}
.wrap{{max-width:760px;margin:0 auto;padding:0 24px 96px;}}
.masthead{{padding:40px 0 24px;border-bottom:1px solid var(--rule);margin-bottom:40px;}}
.eyebrow{{font-family:var(--mono);font-size:11.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-faint);display:flex;align-items:center;gap:10px;margin-bottom:14px;}}
.eyebrow .dot{{width:5px;height:5px;border-radius:50%;background:var(--accent-add);}}
h1.masthead-title{{font-family:var(--sans);font-weight:700;font-size:clamp(24px,4vw,32px);letter-spacing:-.01em;margin:0 0 6px;text-wrap:balance;}}
.masthead-sub{{font-family:var(--sans);color:var(--ink-dim);font-size:15px;margin:0 0 22px;}}
.masthead-sub em{{font-style:italic;color:var(--ink);}}
.stats{{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:20px;}}
.stat{{font-family:var(--mono);font-size:12px;color:var(--ink-dim);background:var(--paper-raised);border:1px solid var(--rule);border-radius:5px;padding:5px 10px;font-variant-numeric:tabular-nums;}}
.stat b{{color:var(--ink);font-weight:500;}}
.stat.add{{border-color:var(--accent-add);color:var(--accent-add);}}
.editors-note{{margin-top:24px;padding:14px 16px;background:var(--paper-raised);border-left:3px solid var(--link);border-radius:0 6px 6px 0;font-family:var(--sans);font-size:13.5px;line-height:1.6;color:var(--ink-dim);}}
.editors-note b{{color:var(--ink);font-weight:600;}}
article{{font-size:18px;}}
article h1.doc-title{{font-family:var(--sans);font-weight:700;font-size:clamp(26px,4.5vw,36px);text-wrap:balance;margin:0 0 28px;letter-spacing:-.01em;}}
article h2{{font-family:var(--sans);font-weight:600;font-size:21px;margin:44px 0 14px;letter-spacing:-.005em;}}
article h3{{font-family:var(--sans);font-weight:600;font-size:15px;color:var(--ink-dim);text-transform:uppercase;letter-spacing:.04em;margin:28px 0 10px;}}
article p{{margin:0 0 20px;max-width:66ch;}}
article a{{color:var(--link);text-decoration-thickness:1px;text-underline-offset:2px;}}
article a:hover{{text-decoration-thickness:2px;}}
pre.mermaid{{background:var(--paper-raised);border:1px solid var(--rule);border-radius:8px;padding:16px;margin:20px 0 28px;overflow-x:auto;}}
.edit{{position:relative;}}
.edit del{{color:var(--accent-cut);background:var(--accent-cut-bg);text-decoration:line-through;text-decoration-color:var(--accent-cut);text-decoration-thickness:1.5px;border-radius:3px;padding:0 2px;box-decoration-break:clone;-webkit-box-decoration-break:clone;}}
.edit ins{{color:var(--accent-add);background:var(--accent-add-bg);text-decoration:none;border-radius:3px;padding:0 2px;box-decoration-break:clone;-webkit-box-decoration-break:clone;font-weight:500;}}
.edit::after{{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--link);vertical-align:super;margin-left:3px;}}
body.clean-view .edit del,body.clean-view .edit::after{{display:none;}}
body.clean-view .edit ins{{color:inherit;background:none;font-weight:inherit;padding:0;}}
.apparatus{{margin-top:64px;}}
.apparatus-head{{font-family:var(--sans);font-weight:700;font-size:22px;margin:0 0 6px;}}
.apparatus-sub{{font-family:var(--sans);color:var(--ink-dim);font-size:14px;margin:0 0 28px;max-width:60ch;}}
.group-label{{font-family:var(--mono);font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;margin:36px 0 12px;display:flex;align-items:center;gap:8px;}}
.group-label .n{{background:var(--paper-raised);border:1px solid var(--rule);border-radius:20px;padding:1px 8px;color:var(--ink-dim);}}
.group-label.rewrite{{color:var(--accent-add);}}
.group-label.skip{{color:var(--accent-skip);}}
.card{{background:var(--paper-raised);border:1px solid var(--rule);border-radius:9px;padding:16px 18px;margin-bottom:10px;box-shadow:var(--shadow);}}
.card-top{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:8px;}}
.card-id{{font-family:var(--mono);font-size:11px;color:var(--ink-faint);}}
.card-kind{{font-family:var(--sans);font-size:11px;font-weight:600;padding:2px 8px;border-radius:20px;}}
.card-kind.rewrite{{background:var(--accent-add-bg);color:var(--accent-add);}}
.card-kind.skip{{background:var(--accent-skip-bg);color:var(--accent-skip);}}
.card-diff{{font-family:var(--serif);font-size:15px;line-height:1.55;margin:8px 0;}}
.card-diff del{{color:var(--accent-cut);background:var(--accent-cut-bg);text-decoration:line-through;border-radius:3px;padding:0 2px;}}
.card-diff ins{{color:var(--accent-add);background:var(--accent-add-bg);text-decoration:none;border-radius:3px;padding:0 2px;}}
.card-reason{{font-family:var(--sans);font-size:13.5px;color:var(--ink-dim);margin:0;}}
.card-quote{{font-family:var(--serif);font-style:italic;font-size:15px;color:var(--ink-dim);margin:8px 0;}}
.rescan{{margin-top:56px;padding:18px 20px;background:var(--paper-raised);border:1px solid var(--rule);border-radius:9px;box-shadow:var(--shadow);}}
.rescan-table{{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:13px;font-variant-numeric:tabular-nums;}}
.rescan-table th{{text-align:right;font-weight:500;color:var(--ink-faint);text-transform:uppercase;font-size:10.5px;letter-spacing:.06em;padding:4px 0 8px;}}
.rescan-table td{{padding:6px 0;border-top:1px solid var(--rule);text-align:right;}}
.rescan-table td:first-child,.rescan-table th:first-child{{text-align:left;font-family:var(--sans);color:var(--ink);}}
.rescan-table td:nth-child(3){{color:var(--accent-add);font-weight:500;}}
footer{{margin-top:32px;padding-top:20px;border-top:1px solid var(--rule);font-family:var(--mono);font-size:11.5px;color:var(--ink-faint);}}
@media (max-width:520px){{.wrap{{padding:0 16px 72px;}} article{{font-size:16.5px;}}}}
</style>
<div class="wrap">
  <div class="masthead">
    <div class="eyebrow"><span class="dot"></span>{eyebrow}</div>
    <h1 class="masthead-title">{title}</h1>
    <p class="masthead-sub">{subtitle}</p>
    {stats}
    <div class="view-toggle" role="group" aria-label="Article view">
      <button type="button" id="btn-redline" class="active" onclick="setView('redline')" style="appearance:none;border:1px solid var(--rule-strong);border-radius:7px 0 0 7px;background:var(--ink);color:var(--paper);font-family:var(--sans);font-size:13px;font-weight:600;padding:8px 16px;cursor:pointer;">Redline</button><button type="button" id="btn-clean" onclick="setView('clean')" style="appearance:none;border:1px solid var(--rule-strong);border-left:0;border-radius:0 7px 7px 0;background:var(--paper-raised);color:var(--ink-dim);font-family:var(--sans);font-size:13px;font-weight:600;padding:8px 16px;cursor:pointer;">Clean copy</button>
    </div>
    {note}
  </div>
  <article id="article-root">
{article_body}
  </article>
  {apparatus}
{rescan}
  <footer>
    {footer}
  </footer>
</div>
<script>
function setView(v){{
  document.body.classList.toggle('clean-view', v==='clean');
  document.getElementById('btn-redline').classList.toggle('active', v==='redline');
  document.getElementById('btn-clean').classList.toggle('active', v==='clean');
}}
</script>
"""


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    spec = json.loads(input_path.read_text(encoding="utf-8"))

    draft_text = Path(spec["draft_path"]).read_text(encoding="utf-8")

    rewrites = spec.get("rewrites", [])
    for r in rewrites:
        r["originalExcerpt"] = draft_text[r["span"]["start"] : r["span"]["end"]]

    patched_text = apply_rewrites(draft_text, rewrites)
    article_body = markdown_to_html(patched_text)

    page = PAGE_TEMPLATE.format(
        title=html.escape(spec.get("title", "Editorial Redline")),
        eyebrow=html.escape(spec.get("eyebrow", "papyrus editorial diagnose")),
        subtitle=spec.get("subtitle", ""),
        stats=render_stats(spec.get("stats")),
        note=render_note(spec.get("note_html")),
        article_body=article_body,
        apparatus=render_apparatus(rewrites, spec.get("skipGroups", [])),
        rescan=render_rescan(spec.get("rescan")),
        footer=spec.get("footer", ""),
    )

    output_path.write_text(page, encoding="utf-8")
    print(f"wrote {output_path} ({len(page)} chars)")


if __name__ == "__main__":
    main()
