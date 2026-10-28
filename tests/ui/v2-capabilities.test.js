const { test } = require('node:test');
const assert = require('node:assert/strict');
test('connection capabilities display all supported transport flags', () => {
  const { capabilities } = require('../../v2-capabilities.js');
  assert.equal(capabilities({ rest: true, flight: true, streaming: true, bind_parameters: false }),
    'rest: yes · flight: yes · streaming: yes · bind parameters: no');
});
