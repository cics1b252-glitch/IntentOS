import test from 'node:test';
import assert from 'node:assert/strict';
import { runRecoverable } from './recovery.js';

test('unexpected bridge exit always releases loading and enables retry', async () => {
  const state = { busy: false, error: '', retry: false, finalizations: 0 };
  const result = await runRecoverable(
    () => Promise.reject(Object.assign(new Error('Bridge encerrada.'), {code: 'bridge_unavailable'})),
    {
      onStart: () => { state.busy = true; },
      onError: error => { state.error = error.message; state.retry = true; },
      onFinally: () => { state.busy = false; state.finalizations += 1; },
    },
  );
  assert.equal(result, null);
  assert.deepEqual(state, {busy: false, error: 'Bridge encerrada.', retry: true, finalizations: 1});
});

test('timeout and Unicode diagnostics also finalize exactly once', async () => {
  let busy = false;
  let diagnostic = '';
  let finalizations = 0;
  await runRecoverable(
    () => Promise.reject(Object.assign(new Error('Tempo excedido 📊 — 日本語'), {code: 'bridge_timeout'})),
    {
      onStart: () => { busy = true; },
      onError: error => { diagnostic = `${error.code}/${error.message}`; },
      onFinally: () => { busy = false; finalizations += 1; },
    },
  );
  assert.equal(busy, false);
  assert.equal(finalizations, 1);
  assert.match(diagnostic, /bridge_timeout.*📊.*日本語/);
});
