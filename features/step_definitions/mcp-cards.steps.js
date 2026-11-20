const { Given, When, Then, setDefaultTimeout } = require('@cucumber/cucumber');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const path = require('node:path');
setDefaultTimeout(30000);
let checks;
function run() {
  return checks ??= (async () => {
    const cwd = path.resolve(__dirname, '../..');
    await promisify(execFile)(process.execPath, ['--import', 'tsx', 'scripts/test-mcp-cards.ts'], { cwd });
    await promisify(execFile)(process.execPath, ['--import', 'tsx', 'scripts/test-mcp-cards-browser.ts'], { cwd });
  })();
}
for (const step of ['a host with seeded reference and story results', 'a host with a seeded reference at revision 3', 'a host that cannot display an app', 'a host with a Story and open reviews']) Given(step, function () {});
for (const step of ['it opens the reference card and navigates to a related story', 'the staff member decides the reference after it has changed', 'the staff member answers a review that has changed']) When(step, function () {});
for (const step of ['the card shows the records and their provenance as text', 'evidence and the next story step can be requested through the host', 'the card reports the stale state and refreshes the reference', 'the card never receives a bearer token', 'the tool retains its text and structured result', 'the card refreshes the review before allowing another answer', 'publish gates and reviews without a revision have no answer controls']) Then(step, async function () { await run(); });
