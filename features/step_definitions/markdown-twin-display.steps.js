const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { Given, When, Then } = require('@cucumber/cucumber');

const source = fs.readFileSync(path.join(__dirname, '../../amplify/publication/markdown-content-type.js'), 'utf8');
const handler = new Function(`${source}\nreturn handler;`)();

function answer(world, accept) {
  const headers = accept === null ? {} : { accept: { value: accept } };
  const response = { statusCode: 200, headers: { 'content-type': { value: world.storedType } } };
  const sent = handler({ request: { uri: '/x/index.md', headers }, response }).headers;
  world.answers.push(sent);
  return sent;
}

Given('a Markdown twin stored as {string}', function (type) {
  this.storedType = type;
  this.answers = [];
});
Given('a page stored as {string}', function (type) {
  this.storedType = type;
});
When('a viewer asks for the twin with the Accept header {string}', function (accept) {
  answer(this, accept);
});
When('a viewer asks for the twin with no Accept header', function () {
  answer(this, null);
});
Then('the twin is sent as {string}', function (type) {
  assert.equal(this.answers[this.answers.length - 1]['content-type'].value, type);
});
Then('the twin is sent without an attachment header', function () {
  assert.equal(this.answers[this.answers.length - 1]['content-disposition'], undefined);
});
Then('both responses say they vary on {string}', function (name) {
  assert.equal(this.answers.length, 2);
  for (const sent of this.answers) assert.equal(sent.vary.value, name);
});
