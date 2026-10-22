import cf from "cloudfront";

const redirectStore = cf.kvs();

async function lookUpRedirectTarget(uri) {
  try {
    const target = await redirectStore.get(uri);
    return target ? String(target) : null;
  } catch (error) {
    return null;
  }
}

function rewriteToIndexDocument(uri) {
  if (uri === "/404") {
    return "/404.html";
  }
  if (uri.endsWith("/")) {
    return uri + "index.html";
  }
  const lastSegment = uri.substring(uri.lastIndexOf("/") + 1);
  if (lastSegment.indexOf(".") === -1) {
    return uri + "/index.html";
  }
  return uri;
}

// Pattern redirects: data from the site's projection.json, spliced between the markers at deploy
// time by redirect-rules.ts. Each rule is {p: regex, t: target with $1..$9, s: status, x: excluded paths}.
const patternRules = /*PAPYRUS_PATTERN_RULES*/[]/*END_PAPYRUS_PATTERN_RULES*/;

function lookUpPatternRedirect(uri) {
  for (let index = 0; index < patternRules.length; index += 1) {
    const rule = patternRules[index];
    if (rule.x.indexOf(uri) !== -1) {
      continue;
    }
    const match = new RegExp(rule.p).exec(uri);
    if (match !== null) {
      return {
        status: rule.s,
        target: rule.t.replace(/\$([0-9])/g, function (whole, group) {
          return match[Number(group)] || "";
        }),
      };
    }
  }
  return null;
}

// Content negotiation for agents: when the site publishes Markdown twins (standard front end, agents.markdown), a request
// whose Accept header prefers text/markdown over text/html is rewritten to the .md object before the cache lookup. The
// flag is spliced in by redirect-rules.ts at deploy time.
const negotiateMarkdown = /*PAPYRUS_NEGOTIATE_MARKDOWN*/false/*END_PAPYRUS_NEGOTIATE_MARKDOWN*/;

function qualityOf(accept, mediaType) {
  let quality = 0;
  const parts = accept.toLowerCase().split(",");
  for (let index = 0; index < parts.length; index += 1) {
    const fields = parts[index].split(";");
    if (fields[0].trim() !== mediaType) {
      continue;
    }
    quality = 1;
    for (let field = 1; field < fields.length; field += 1) {
      const pair = fields[field].trim();
      if (pair.indexOf("q=") === 0) {
        quality = Number(pair.substring(2));
        if (isNaN(quality)) {
          quality = 0;
        }
      }
    }
  }
  return quality;
}

function prefersMarkdown(request) {
  const header = request.headers && request.headers.accept;
  if (!header || !header.value) {
    return false;
  }
  const markdown = qualityOf(header.value, "text/markdown");
  return markdown > 0 && markdown > qualityOf(header.value, "text/html");
}

function markdownTwin(uri) {
  if (uri === "/404.html" || uri.length < 6 || uri.substring(uri.length - 5) !== ".html") {
    return null;
  }
  return uri.substring(0, uri.length - 5) + ".md";
}

// Directory-style sites keep a page's twin at /x/index.md, so a bare /x.md is rewritten there. The edge cannot test for
// existence, hence the rule: a last segment <name>.md with a name other than index. A path prefix (a base path) is just
// part of <path>. The flag is spliced in by redirect-rules.ts at deploy time from urls.style.
const directoryTwins = /*PAPYRUS_DIRECTORY_TWINS*/false/*END_PAPYRUS_DIRECTORY_TWINS*/;

function directoryTwin(uri) {
  if (uri.length < 5 || uri.substring(uri.length - 3) !== ".md") {
    return null;
  }
  const lastSegment = uri.substring(uri.lastIndexOf("/") + 1);
  if (lastSegment === "index.md" || lastSegment === ".md") {
    return null;
  }
  return uri.substring(0, uri.length - 3) + "/index.md";
}

async function handler(event) {
  const request = event.request;
  const redirectTarget = await lookUpRedirectTarget(request.uri);
  if (redirectTarget !== null) {
    return {
      statusCode: 301,
      statusDescription: "Moved Permanently",
      headers: { location: { value: redirectTarget } },
    };
  }
  const patternRedirect = lookUpPatternRedirect(request.uri);
  if (patternRedirect !== null) {
    return {
      statusCode: patternRedirect.status,
      statusDescription: "Moved",
      headers: { location: { value: patternRedirect.target } },
    };
  }
  request.uri = rewriteToIndexDocument(request.uri);
  if (directoryTwins) {
    const bareTwin = directoryTwin(request.uri);
    if (bareTwin !== null) {
      request.uri = bareTwin;
    }
  }
  if (negotiateMarkdown && prefersMarkdown(request)) {
    const twin = markdownTwin(request.uri);
    if (twin !== null) {
      request.uri = twin;
    }
  }
  return request;
}
