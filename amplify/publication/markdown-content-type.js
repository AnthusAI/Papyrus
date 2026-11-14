// CloudFront viewer-response function: show a Markdown twin in a browser instead of downloading it (PPY-40f96a).
//
// The projection stores every twin (/x/index.md) as text/markdown, and Safari downloads that type. A browser that follows a
// link to a twin sends an Accept header that lists text/html; it is sent the same bytes as text/plain; charset=utf-8, which
// every browser displays. A client whose Accept header prefers text/markdown (an agent, a script, redirect-and-index.js
// rewriting /x/ to the twin), and a client that names no type at all (curl, fetch with */*), still gets text/markdown.
//
// The function runs after the cache, on every response, so it changes what one viewer is sent and never what is cached: the
// object and its cache key stay as they are, and a browser cannot make a Markdown client's cached response plain text or the
// other way round. The response says Vary: Accept so a shared cache in between keeps the two apart. The function sets no
// attachment header, so a browser shows the text. Only a response whose content type is text/markdown is touched.

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

function acceptOf(request) {
  const header = request && request.headers && request.headers.accept;
  return header && header.value ? header.value : "";
}

// True for a browser navigation: Accept lists text/html and ranks text/markdown below it (a browser does not name it at all).
// A client that ranks the two equally asked for the twin and keeps text/markdown.
function isBrowser(request) {
  const accept = acceptOf(request);
  const html = qualityOf(accept, "text/html");
  return html > 0 && qualityOf(accept, "text/markdown") < html;
}

function addVaryAccept(headers) {
  const existing = headers.vary && headers.vary.value ? headers.vary.value : "";
  if (existing.toLowerCase().split(",").map(function (name) { return name.trim(); }).indexOf("accept") === -1) {
    headers.vary = { value: existing === "" ? "Accept" : existing + ", Accept" };
  }
}

function handler(event) {
  const response = event.response;
  const headers = response.headers;
  const contentType = headers["content-type"] && headers["content-type"].value ? headers["content-type"].value.toLowerCase() : "";
  if (contentType.indexOf("text/markdown") !== 0) {
    return response;
  }
  if (isBrowser(event.request)) {
    headers["content-type"] = { value: "text/plain; charset=utf-8" };
  }
  addVaryAccept(headers);
  return response;
}
