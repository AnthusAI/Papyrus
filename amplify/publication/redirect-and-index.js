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
  request.uri = rewriteToIndexDocument(request.uri);
  return request;
}
