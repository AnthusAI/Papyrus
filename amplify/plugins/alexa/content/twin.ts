/**
 * The page-facts header of an article's Markdown twin (`item_markdown` in src/papyrus_content/projection/standard/markdown.py):
 *
 *     # Title                       (only when the body does not open with a heading)
 *     > the summary
 *     By <authors> · Published <date> · Updated <date>
 *     Canonical: <url>
 *     <the Markus body, verbatim>
 *
 * `splitTwin` returns the facts and the body. The body is what remains, byte for byte.
 */
export type TwinParts = { title?: string; summary?: string; byline?: string; canonical?: string; body: string };

function plainLinks(text: string): string {
  return text.replace(/\[([^\]]*)\]\([^)]*\)/g, "$1");
}

export function splitTwin(text: string): TwinParts {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  let index = 0;
  const skipBlank = () => {
    while (index < lines.length && lines[index].trim() === "") index += 1;
  };
  const parts: Omit<TwinParts, "body"> = {};

  skipBlank();
  const heading = /^#\s+(.+?)\s*$/.exec(lines[index] ?? "");
  if (heading) {
    parts.title = heading[1];
    index += 1;
    skipBlank();
  }
  if ((lines[index] ?? "").startsWith(">")) {
    const quoted: string[] = [];
    while (index < lines.length && lines[index].startsWith(">")) {
      quoted.push(lines[index].replace(/^>\s?/, ""));
      index += 1;
    }
    parts.summary = quoted.join(" ").trim();
    skipBlank();
  }
  if (/^(By |Published )/.test(lines[index] ?? "")) {
    const by = /^By (.+?)(?:\s·\s(?:Published|Updated)\b.*)?$/.exec(plainLinks(lines[index]));
    if (by) parts.byline = by[1];
    index += 1;
    skipBlank();
  }
  const canonical = /^Canonical:\s*(\S+)\s*$/.exec(lines[index] ?? "");
  if (canonical) {
    parts.canonical = canonical[1];
    index += 1;
    skipBlank();
  }
  return { ...parts, body: lines.slice(index).join("\n") };
}
