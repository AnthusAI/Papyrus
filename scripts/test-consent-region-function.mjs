// Run with: node --test scripts/test-consent-region-function.mjs
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { handler, consentAnswer, NOTICE_COUNTRIES } = require('../infra/edge/consent-region-function.js');

const event = (headers) => ({ request: { headers } });
const answer = (response) => JSON.parse(response.body);

test('a viewer in a listed country needs the notice', () => {
  const response = handler(event({ 'cloudfront-viewer-country': { value: 'DE' } }));
  assert.deepEqual(answer(response), { country: 'DE', notice: true });
  assert.equal(response.statusCode, 200);
});

test('a viewer in an unlisted country does not', () => {
  assert.deepEqual(answer(handler(event({ 'cloudfront-viewer-country': { value: 'US' } }))), { country: 'US', notice: false });
});

test('the answer is never cached and is JSON', () => {
  const { headers } = handler(event({ 'cloudfront-viewer-country': { value: 'US' } }));
  assert.equal(headers['cache-control'].value, 'private, no-store');
  assert.match(headers['content-type'].value, /^application\/json/);
});

test('a missing, empty, malformed or non-country header fails closed', () => {
  for (const headers of [{}, { 'cloudfront-viewer-country': { value: '' } }, { 'cloudfront-viewer-country': { value: 'Germany' } }, { 'cloudfront-viewer-country': { value: 'T1' } }, { 'cloudfront-viewer-country': { value: 'XX1' } }]) {
    assert.deepEqual(answer(handler(event(headers))), { country: '', notice: true }, JSON.stringify(headers));
  }
});

test('the header is matched case-insensitively on the value', () => {
  assert.equal(consentAnswer('gb', NOTICE_COUNTRIES).notice, true);
});

test('the region list is passed in, so a site can replace it', () => {
  assert.deepEqual(consentAnswer('US', ['US']), { country: 'US', notice: true });
  assert.deepEqual(consentAnswer('DE', ['US']), { country: 'DE', notice: false });
  assert.deepEqual(consentAnswer('DE', []), { country: 'DE', notice: false });
});

test('the generated list holds only two-letter country codes', () => {
  assert.ok(NOTICE_COUNTRIES.length > 0);
  for (const code of NOTICE_COUNTRIES) assert.match(code, /^[A-Z]{2}$/);
});
