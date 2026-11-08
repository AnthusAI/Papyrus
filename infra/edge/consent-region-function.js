// Reference implementation, NOT deployed and NOT wired into any distribution (see infra/edge/README.md,
// "Consent region function"). A CloudFront Function (runtime cloudfront-js-2.0, viewer-request) that answers the
// consent address (default /_papyrus/consent) straight from the edge:
//
//   {"country":"DE","notice":true}
//
// `notice` is false only for a viewer whose country is known and is not in the notice list. It fails closed: with no
// usable country header the answer is {"country":"","notice":true}. The answer is never cached and nothing is logged.
//
// The list between the markers is GENERATED from the one Python constant
// (papyrus_content.markus_renderer.consent.CONSENT_DENIED_BY_DEFAULT_REGIONS, plus a site's own overrides) by
// infra/edge/generate_consent_region_function.py. Do not edit it by hand; a test fails if it drifts.
// The list is a policy choice that the site owner or legal owns. It is not legal advice and it must be reviewed.

// BEGIN GENERATED NOTICE COUNTRIES
var NOTICE_COUNTRIES = ["AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR","HU","IE","IT","LV","LT","LU","MT","NL","PL","PT","RO","SK","SI","ES","SE","IS","LI","NO","GB","CH"];
// END GENERATED NOTICE COUNTRIES

var NON_COUNTRY_CODES = ['XX', 'ZZ', 'AP', 'EU', 'UN'];

function consentAnswer(countryHeader, noticeCountries) {
  var country = typeof countryHeader === 'string' ? countryHeader.toUpperCase() : '';
  // absent, malformed, a non-country marker such as T1 (Tor) or A1/A2, or an ISO user-assigned/reserved code that
  // geolocation databases use for "unknown" (XX, ZZ, AP, EU, UN): unknown, so the notice is shown
  if (!/^[A-Z]{2}$/.test(country) || NON_COUNTRY_CODES.indexOf(country) !== -1) country = '';
  return { country: country, notice: country === '' || noticeCountries.indexOf(country) !== -1 };
}

function handler(event) {
  var header = event.request.headers['cloudfront-viewer-country'];
  var answer = consentAnswer(header ? header.value : '', NOTICE_COUNTRIES);
  return {
    statusCode: 200,
    statusDescription: 'OK',
    headers: {
      'content-type': { value: 'application/json; charset=utf-8' },
      'cache-control': { value: 'private, no-store' },
    },
    body: JSON.stringify(answer),
  };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { handler: handler, consentAnswer: consentAnswer, NOTICE_COUNTRIES: NOTICE_COUNTRIES };
}
