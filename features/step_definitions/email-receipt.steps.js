const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { Given, When, Then } = require('@cucumber/cucumber');

Given('a synthetic email receipt API that refuses overview reads', function () {
  this.receiptBoundaryResult = null;
});
When('the editor opens known, empty, denied, unavailable, and superseded receipts', function () {
  this.receiptBoundaryResult = execFileSync(process.execPath, ['scripts/test-monitoring-receipt.cjs'], { encoding: 'utf8' });
});
Then('each email request stays confined to the selected receipt', function () {
  assert.match(this.receiptBoundaryResult, /PASS: exact receipt/);
});
Then('no monitoring overview or refresh timer is started', function () {
  assert.match(this.receiptBoundaryResult, /PASS: exact receipt/);
});
