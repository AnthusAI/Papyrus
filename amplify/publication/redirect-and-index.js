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
  return request;
}
