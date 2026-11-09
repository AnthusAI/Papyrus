"""A site's own hooks, written the way Pilobolus's are: the site lifts an Instagram ::video line before Markus runs and draws its own embed after.

This is a regression fixture (features_backend/video-embed.feature): Papyrus core must leave this directive alone."""
import re

LINE = re.compile(r'^::video\{src="(https://www\.instagram\.com/[^"]+)" title="([^"]*)"\}[ \t]*$', re.M)
FOUND = []


def source(summary, text, site):
    def lift(match):
        FOUND.append((match.group(1), match.group(2)))
        return f"PILOINSTAGRAMTOKEN{len(FOUND) - 1}"

    return LINE.sub(lift, text)


def item_decorator(html, summary):
    def draw(match):
        address, title = FOUND[int(match.group(1))]
        return (f'<div class="pilo-instagram"><blockquote class="instagram-media" data-instgrm-permalink="{address}">'
                f'<a href="{address}">{title}</a></blockquote></div>')

    return re.sub(r"<p>PILOINSTAGRAMTOKEN(\d+)</p>", draw, html)
