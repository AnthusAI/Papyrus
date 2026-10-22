"""Write a preview of a sample email: ``python -m papyrus_content.email_render OUT.html``."""

from __future__ import annotations

import sys
from pathlib import Path

from . import EmailFooter, EmailTheme, render_issue

SAMPLE = """# Weekly roundup

Welcome back. This week: **three** stories, one [link](/archive/one) and a picture.

## Highlights

- First item with a [relative link](/archive/first)
- Second item
  - nested item

> A pull quote that should stay readable on a phone.

![A placeholder](/images/sample.png)

| Story | Section |
|---|---|
| One | News |
| Two | Notes |

```
code block
```
"""


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m papyrus_content.email_render OUT.html", file=sys.stderr)
        return 2
    theme = EmailTheme(accent="#b3261e", text="#222222", background="#f1ece4", site_name="Example Times")
    footer = EmailFooter(
        site_name="Example Times", site_url="https://example.com/", reason="You get this because you subscribed on example.com.",
        manage_url="https://example.com/manage", unsubscribe_url="https://example.com/unsub", postal_address="1 Example Way\nExample City, EX 00000",
    )
    mail = render_issue(subject="Weekly roundup", markus=SAMPLE, theme=theme, footer=footer, preheader="Three stories", site_url="https://example.com/")
    Path(argv[0]).write_text(mail.html, encoding="utf-8")
    Path(argv[0]).with_suffix(".txt").write_text(mail.text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
