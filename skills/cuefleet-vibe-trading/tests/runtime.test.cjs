'use strict';

const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const fs = require('node:fs/promises');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { run, VERSION } = require('../scripts/runtime.cjs');

const NOW = 1_768_865_600_000;
const KEY = 'ef1_' + 't'.repeat(43);
const ACCOUNT = '00000000-0000-4000-8000-000000000010';
const intent = (mode = 'simulation') => ({ version: VERSION, requestId: randomUUID(), mode, symbol: 'ETHUSDT', period: '30m', amount: '5',
  signal: { decision: 'LONG', observedAt: NOW - 1_000 } });
const receipt = input => ({ version: VERSION, requestId: input.requestId, mode: input.mode });

async function mock(t, { mode = 'simulation', updateStatus, sendOrder, getReceipt } = {}) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'cuefleet-vibe-runtime-'));
  const calls = [];
  const respond = (res, status, body) => res.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(body));
  const accepted = (id, executionMode = mode) => ({ ok: true, data: { id, executionMode, state: 'accepted', attempted: true, orderId: '90071992547409931234' } });
  const server = http.createServer(async (req, res) => {
    let raw = '';
    for await (const chunk of req) raw += chunk;
    const entry = { method: req.method, url: req.url, headers: req.headers, body: raw ? JSON.parse(raw) : null };
    calls.push(entry);
    if (req.url === '/v1/status') {
      const data = { executionMode: mode, access: { allowed: true, kind: 'vip' },
        accounts: [{ id: ACCOUNT, apiEligible: true, canTrade: true, stale: false, state: 'ready' }] };
      updateStatus?.(data);
      return respond(res, 200, { ok: true, data });
    }
    if (req.url === '/v1/accounts/' + ACCOUNT + '/market') {
      return respond(res, 200, { ok: true, data: { state: 'ready', blocked: false,
        catalog: [{ symbol: 'ETHUSDT', periods: [{ period: 'THIRTY_MINUTE', long: '0.8', short: '0.79' }] }] } });
    }
    if (req.url === '/v1/orders') {
      return sendOrder ? sendOrder(res, respond, entry) : respond(res, 201, accepted(entry.headers['idempotency-key']));
    }
    if (req.url.startsWith('/v1/requests/')) {
      const id = req.url.split('/').at(-1);
      return getReceipt ? getReceipt(res, respond, id) : respond(res, 200, accepted(id));
    }
    respond(res, 404, { ok: false });
  });
  await new Promise((resolve, reject) => server.once('error', reject).listen(0, '127.0.0.1', resolve));
  t.after(async () => {
    await new Promise(resolve => server.close(resolve));
    for (const name of await fs.readdir(directory)) await fs.unlink(path.join(directory, name));
    await fs.rmdir(directory);
  });
  return { calls, directory, options: { now: () => NOW, env: { CUEFLEET_API_PORT: String(server.address().port),
    CUEFLEET_API_KEY: KEY, CUEFLEET_VIBE_STATE_DIR: directory } } };
}

for (const mode of ['simulation', 'live']) {
  test(`${mode} uses named console mode, original UUID and quoted payout`, async t => {
    const fixture = await mock(t, { mode });
    const input = intent(mode);
    if (mode === 'live') input.signal.decision = 'SHORT';
    const result = await run('run', input, fixture.options);
    assert.deepEqual(result, { ...receipt(input), state: 'accepted', attempted: true, orderId: '90071992547409931234' });
    assert.deepEqual(fixture.calls.map(call => call.url), ['/v1/status', '/v1/accounts/' + ACCOUNT + '/market', '/v1/orders']);
    assert.ok(fixture.calls.every(call => call.headers.authorization === 'Bearer ' + KEY && call.headers['x-cuefleet-execution-mode'] === mode));
    const order = fixture.calls.at(-1);
    assert.equal(order.headers['idempotency-key'], input.requestId);
    assert.equal(order.headers['x-cuefleet-observed-at'], String(input.signal.observedAt));
    assert.deepEqual(order.body, { accountId: ACCOUNT, symbol: 'ETHUSDT', period: '30m', direction: input.signal.decision,
      amount: '5', payoutRatio: mode === 'live' ? '0.79' : '0.8', wallet: 'UM' });
    assert.equal(await fs.readFile(path.join(fixture.directory, input.requestId + '.claim'), 'utf8'), mode + '\n');
    assert.doesNotMatch(JSON.stringify(result), /ef1_/);
  });
}

test('NO_SIGNAL runs without credentials and model extras cannot change execution parameters', async () => {
  const input = intent();
  input.signal.decision = 'NO_SIGNAL';
  assert.equal((await run('run', input, { env: {} })).state, 'no_signal');
  input.signal.amount = '100';
  await assert.rejects(run('run', input, { env: {} }), /invalid_input/);
});

test('legacy console, mode mismatch and trial all block before quote or submit', async t => {
  const legacy = await mock(t, { updateStatus: data => { delete data.executionMode; } });
  await assert.rejects(run('run', intent(), legacy.options), /execution_mode_unsupported/);
  assert.deepEqual(legacy.calls.map(call => call.url), ['/v1/status']);

  const live = await mock(t, { mode: 'live' });
  await assert.rejects(run('run', intent(), live.options), /execution_mode_mismatch/);
  assert.deepEqual(live.calls.map(call => call.url), ['/v1/status']);

  const trial = await mock(t, { updateStatus: data => { data.access.kind = 'trial'; } });
  await assert.rejects(run('run', intent(), trial.options), /vip_required/);
  assert.deepEqual(trial.calls.map(call => call.url), ['/v1/status']);
});

test('directional signals older than 30 seconds or reporting a future observation are rejected', async t => {
  const fixture = await mock(t);
  for (const observedAt of [NOW - 30_001, NOW + 1]) {
    const input = intent();
    input.signal.observedAt = observedAt;
    await assert.rejects(run('run', input, fixture.options), /signal_expired/);
  }
  assert.equal(fixture.calls.length, 0);
});

test('mode changes between status and submission are rejected by the console', async t => {
  const fixture = await mock(t, { sendOrder: (res, respond) => respond(res, 409, { ok: false, error: { code: 'execution_mode_mismatch' } }) });
  const result = await run('run', intent(), fixture.options);
  assert.equal(result.state, 'blocked');
  assert.equal(result.reason, 'execution_mode_mismatch');
  assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 1);
});

test('disconnect reconciles the same UUID and concurrent or later runs cannot POST it again', async t => {
  const fixture = await mock(t, { sendOrder: res => res.destroy(),
    getReceipt: (res, respond) => respond(res, 404, { ok: false, error: { code: 'request_not_found' } }) });
  const input = intent();
  const outcomes = await Promise.all([run('run', input, fixture.options), run('run', input, fixture.options)]);
  for (const result of outcomes) assert.deepEqual(result, { ...receipt(input), state: 'unknown', reason: 'receipt_unavailable' });
  assert.equal((await run('run', input, fixture.options)).state, 'unknown');
  assert.equal((await run('receipt', receipt(input), fixture.options)).state, 'unknown');
  assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 1);
  const lookups = fixture.calls.filter(call => call.url.startsWith('/v1/requests/'));
  assert.ok(lookups.length >= 4);
  assert.ok(lookups.every(call => call.url === '/v1/requests/' + input.requestId));
});

test('receipt reconciles original modes even if the status mode has changed', async t => {
  const input = intent();
  const fixture = await mock(t, { mode: 'live',
    getReceipt: (res, respond, id) => respond(res, 200, { ok: true, data: { id, executionMode: 'simulation', state: 'accepted', orderId: '1' } }) });
  assert.equal((await run('receipt', receipt(input), fixture.options)).state, 'accepted');
  assert.equal((await run('receipt', receipt({ ...input, mode: 'live' }), fixture.options)).state, 'unknown');
  assert.ok(fixture.calls.every(call => call.method === 'GET' && call.url.startsWith('/v1/requests/')));
});

test('an explicit unknown order response resolves by GET to the original accepted receipt', async t => {
  const fixture = await mock(t, { sendOrder: (res, respond, entry) => respond(res, 202,
    { ok: true, data: { id: entry.headers['idempotency-key'], executionMode: 'simulation', state: 'unknown', attempted: null } }) });
  const input = intent();
  const result = await run('run', input, fixture.options);
  assert.equal(result.state, 'accepted');
  assert.equal(fixture.calls.filter(call => call.method === 'POST').length, 1);
  assert.equal(fixture.calls.at(-1).url, '/v1/requests/' + input.requestId);
});
