const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { Given, When, Then } = require('@cucumber/cucumber');

// One run of the dialog's tests (scripts/test-add-reference.ts); each step checks the named test passed.
let report = null;
function run() {
  if (!report) report = execFileSync(process.execPath, ['--import', 'tsx', '--test', 'scripts/test-add-reference.ts'], { encoding: 'utf8' });
  return report;
}
function passed(name) {
  assert.match(run(), new RegExp(`✔ ${name}`), `test did not pass: ${name}`);
}

Given('an editor with the Add dialog open', function () { run(); });

When('the editor adds an address and makes no decision', function () { });
Then('the address is registered as a pending Reference', function () { passed('With no decision the Reference is only registered'); });
Then('nothing is accepted and nothing is rated', function () { passed('With no decision the Reference is only registered'); });
Then('the dialog says the reference was added and is pending review', function () { passed('With no decision the Reference is only registered'); });

When('the editor adds an address, accepts it and gives it 5 stars', function () { });
Then('the address is registered first', function () { passed('An address is registered first, then accepted, then rated'); });
Then("the same Reference is then accepted with the editor's sentence", function () { passed('An address is registered first, then accepted, then rated'); });
Then('the same Reference is then rated 5 of 5 stars', function () { passed('An address is registered first, then accepted, then rated'); });
Then('the dialog says it was added, accepted and rated', function () { passed('In the browser: accept and a star are chosen with buttons'); });

When('the editor adds an address and gives it 3 stars without accepting', function () {});
Then('the dialog turns Accept on, fills the first three stars and sends no separate accept, because the newsroom accepts a rated pending Reference itself', function () { passed('A rating alone sends no separate accept'); passed('In the browser: accept and a star are chosen with buttons'); });

When('the editor adds an address that is already an accepted Reference', function () {});
Then('the dialog says the address was already a Reference', function () { passed('An address that is already a Reference is reported'); });
Then('it is not accepted a second time', function () { passed('An address that is already a Reference is reported'); });

When('the editor accepts and rates while adding, and both of those saves fail', function () {});
Then('the Reference still exists', function () { passed('When the accept or the rating fails the Reference still exists'); });
Then('the dialog says which step did not save and why', function () { passed('When the accept or the rating fails the Reference still exists'); });

When('the newsroom refuses the address', function () {});
Then('the dialog says the reference was not added', function () { passed('In the browser: accept and a star are chosen with buttons'); });
Then('the address stays in the box', function () { passed('In the browser: accept and a star are chosen with buttons'); });

When('the editor adds an address that is not https, or a rating outside 1 to 5', function () {});
Then('nothing is sent to the newsroom', function () { passed('Nothing is written for an address or rating that is not valid'); });

Then('accepting is a button that reads Accept or Accepted with a check mark', function () { passed('The dialog is buttons with marks and words'); });
Then('the rating is five star buttons with a written summary such as "4 of 5 stars" or "Not rated"', function () { passed('The dialog is buttons with marks and words'); });
Then('pressing the chosen star again clears the rating', function () { passed('In the browser: accept and a star are chosen with buttons'); });
Then('the dialog has no drop-down and no outlines', function () { passed('The dialog is buttons with marks and words'); });
