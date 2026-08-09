import test from 'node:test';
import assert from 'node:assert/strict';
import {formatTimestamp, normalizeTimestamp} from './timestamps.js';

test('normalizes ISO, offsets, Unix seconds, Unix milliseconds and Date', () => {
  const expected = '2024-01-01T00:00:00.000Z';
  assert.equal(normalizeTimestamp('2024-01-01T00:00:00Z'), expected);
  assert.equal(normalizeTimestamp('2023-12-31T21:00:00-03:00'), expected);
  assert.equal(normalizeTimestamp(1704067200), expected);
  assert.equal(normalizeTimestamp(1704067200000), expected);
  assert.equal(normalizeTimestamp(new Date(expected)), expected);
});

test('never renders Invalid Date for missing or invalid values', () => {
  assert.equal(formatTimestamp(undefined), 'Data não informada');
  assert.equal(formatTimestamp('not-a-date'), 'Data não informada');
  assert.doesNotMatch(formatTimestamp(null), /Invalid Date/);
});
