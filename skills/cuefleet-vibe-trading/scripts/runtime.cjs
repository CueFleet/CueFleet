'use strict';

const http = require('node:http');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const VERSION = 'cuefleet.vibe-trading.v1';
const MODES = ['simulation', 'live'];
const PERIODS = { '10m': 'TEN_MINUTE', '30m': 'THIRTY_MINUTE', '1h': 'ONE_HOUR', '1d': 'ONE_DAY' };
const UUID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
const DECIMAL = /^\d{1,24}(?:\.\d{1,18})?$/;
const API_KEY = /^ef1_[A-Za-z0-9_-]{43}$/;
const MAX_AGE = 30_000;
const MAX_RESPONSE = 1024 * 1024;
const TERMINAL = ['accepted', 'rejected', 'blocked'];
const RECEIPT_STATES = [...TERMINAL, 'unknown', 'processing'];
const PRE_SUBMIT_ERRORS = new Set([
  'execution_mode_mismatch', 'invalid_execution_mode', 'invalid_api_key', 'api_read_only',
  'api_vip_required', 'account_not_authorized', 'api_amount_limit', 'invalid_order',
  'client_upgrade_required', 'signal_expired',
]);

class RuntimeError extends Error {}
const fail = code => { throw new RuntimeError(code); };

function fields(value, required, optional = []) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      required.some(key => !Object.hasOwn(value, key)) ||
      Object.keys(value).some(key => !required.includes(key) && !optional.includes(key))) {
    fail('invalid_input');
  }
}

function readInput(action, value) {
  const common = ['version', 'mode', 'requestId'];
  if (action === 'receipt') fields(value, common);
  else if (action === 'run') fields(value, [...common, 'symbol', 'period', 'amount', 'signal'], ['accountId']);
  else fail('invalid_command');

  if (value.version !== VERSION || !MODES.includes(value.mode) ||
      typeof value.requestId !== 'string' || !UUID.test(value.requestId)) fail('invalid_input');

  if (action === 'run') {
    fields(value.signal, ['decision', 'observedAt']);
    if (!['BTCUSDT', 'ETHUSDT'].includes(value.symbol) || !Object.hasOwn(PERIODS, value.period) ||
        typeof value.amount !== 'string' || !DECIMAL.test(value.amount) || Number(value.amount) <= 0 ||
        (Object.hasOwn(value, 'accountId') && (typeof value.accountId !== 'string' || !UUID.test(value.accountId))) ||
        !['LONG', 'SHORT', 'NO_SIGNAL'].includes(value.signal.decision) ||
        !Number.isSafeInteger(value.signal.observedAt) || value.signal.observedAt <= 0) fail('invalid_input');
  }

  return { ...value, requestId: value.requestId.toLowerCase(), accountId: value.accountId?.toLowerCase() };
}

function fresh(observedAt, now) {
  const age = now() - observedAt;
  return Number.isFinite(age) && age >= 0 && age <= MAX_AGE;
}

function createClient(env, mode) {
  const rawPort = env.CUEFLEET_API_PORT ?? '17687';
  const port = Number(rawPort);
  if (!/^\d{4,5}$/.test(rawPort) || !Number.isSafeInteger(port) || port < 1024 || port > 65535) fail('invalid_port');
  const key = env.CUEFLEET_API_KEY;
  if (typeof key !== 'string' || !API_KEY.test(key)) fail('api_key_required');

  return (route, { method = 'GET', body, requestId, observedAt } = {}) => new Promise((resolve, reject) => {
    const serialized = body ? JSON.stringify(body) : null;
    const headers = { Authorization: 'Bearer ' + key, Accept: 'application/json', 'X-CueFleet-Execution-Mode': mode };
    if (serialized) {
      headers['Content-Type'] = 'application/json';
      headers['Content-Length'] = Buffer.byteLength(serialized);
      headers['Idempotency-Key'] = requestId;
      headers['X-CueFleet-Observed-At'] = String(observedAt);
    }
    const request = http.request({ host: '127.0.0.1', port, path: route, method, headers, agent: false,
      signal: AbortSignal.timeout(method === 'POST' ? 15_000 : 8_000) }, response => {
      if (response.statusCode >= 300 && response.statusCode < 400) {
        response.destroy();
        return reject(new RuntimeError('unexpected_redirect'));
      }
      let size = 0;
      const chunks = [];
      response.on('data', chunk => {
        size += chunk.length;
        if (size > MAX_RESPONSE) response.destroy(new RuntimeError('response_too_large'));
        else chunks.push(chunk);
      });
      response.on('error', reject);
      response.on('end', () => {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); }
        catch { reject(new RuntimeError('invalid_response')); }
      });
    });
    request.on('error', reject);
    request.end(serialized);
  });
}

const outcome = (input, state, detail = {}) => ({ version: VERSION, mode: input.mode, requestId: input.requestId, state, ...detail });

function readReceipt(input, value) {
  const data = value?.data;
  if (value?.ok !== true || typeof data?.id !== 'string' || data.id.toLowerCase() !== input.requestId ||
      data.executionMode !== input.mode || !RECEIPT_STATES.includes(data.state)) return null;
  return outcome(input, data.state, {
    attempted: typeof data.attempted === 'boolean' ? data.attempted : null,
    orderId: typeof data.orderId === 'string' && /^[0-9]{1,40}$/.test(data.orderId) ? data.orderId : null,
  });
}

async function reconcile(request, input) {
  try {
    const value = await request('/v1/requests/' + input.requestId);
    return readReceipt(input, value) ?? outcome(input, 'unknown', { reason: 'receipt_unavailable' });
  } catch {
    return outcome(input, 'unknown', { reason: 'receipt_unavailable' });
  }
}

async function recorded(filename) {
  try { await fs.lstat(filename); return true; }
  catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}

async function reserve(filename, mode) {
  await fs.mkdir(path.dirname(filename), { recursive: true, mode: 0o700 });
  let handle;
  try { handle = await fs.open(filename, 'wx', 0o600); }
  catch (error) { if (error.code === 'EEXIST') return false; throw error; }
  try { await handle.writeFile(mode + '\n'); await handle.sync(); }
  finally { await handle.close(); }
  return true;
}

function selectAccount(status, accountId) {
  const accounts = status.accounts;
  if (!Array.isArray(accounts)) fail('console_status_unavailable');
  if (!accountId && accounts.length !== 1) fail('account_selection_required');
  const account = accountId ? accounts.find(item => item?.id === accountId) : accounts[0];
  if (typeof account?.id !== 'string' || !UUID.test(account.id) || account.apiEligible !== true || account.canTrade !== true ||
      account.state !== 'ready' || account.stale !== false) fail('account_unavailable');
  return account.id;
}

async function payoutFor(request, accountId, input) {
  const value = await request('/v1/accounts/' + accountId + '/market');
  if (value?.ok !== true || value.data?.state !== 'ready' || value.data.blocked !== false || !Array.isArray(value.data.catalog)) fail('market_unavailable');
  const item = value.data.catalog.find(product => product?.symbol === input.symbol);
  const period = Array.isArray(item?.periods) && item.periods.find(quote => quote?.period === PERIODS[input.period]);
  const payoutRatio = period?.[input.signal.decision.toLowerCase()];
  if (typeof payoutRatio !== 'string' || !DECIMAL.test(payoutRatio) || Number(payoutRatio) <= 0 || Number(payoutRatio) > 100) fail('market_unavailable');
  return payoutRatio;
}

async function run(action, value, { env = process.env, now = Date.now } = {}) {
  const input = readInput(action, value);
  if (action === 'run' && input.signal.decision === 'NO_SIGNAL') return outcome(input, 'no_signal');
  const request = createClient(env, input.mode);
  if (action === 'receipt') return reconcile(request, input);

  const directory = env.CUEFLEET_VIBE_STATE_DIR ?? path.join(os.homedir(), '.cuefleet', 'vibe-trading', 'requests');
  if (!path.isAbsolute(directory)) fail('invalid_state_directory');
  const filename = path.join(directory, input.requestId + '.claim');
  if (await recorded(filename)) return reconcile(request, input);
  if (!fresh(input.signal.observedAt, now)) fail('signal_expired');

  const status = await request('/v1/status');
  if (status?.ok !== true || !status.data) fail('console_status_unavailable');
  if (!MODES.includes(status.data.executionMode)) fail('execution_mode_unsupported');
  if (status.data.executionMode !== input.mode) fail('execution_mode_mismatch');
  if (status.data.access?.allowed !== true || status.data.access.kind !== 'vip') fail('vip_required');

  const accountId = selectAccount(status.data, input.accountId);
  const payoutRatio = await payoutFor(request, accountId, input);
  if (!fresh(input.signal.observedAt, now)) fail('signal_expired');
  if (!await reserve(filename, input.mode)) return reconcile(request, input);
  if (!fresh(input.signal.observedAt, now)) return outcome(input, 'blocked', { attempted: false, reason: 'signal_expired' });

  const body = { accountId, symbol: input.symbol, period: input.period, direction: input.signal.decision, amount: input.amount, payoutRatio, wallet: 'UM' };
  try {
    const result = await request('/v1/orders', { method: 'POST', body, requestId: input.requestId, observedAt: input.signal.observedAt });
    const receipt = readReceipt(input, result);
    if (receipt && TERMINAL.includes(receipt.state)) return receipt;
    if (result?.ok === false && PRE_SUBMIT_ERRORS.has(result.error?.code)) {
      return outcome(input, 'blocked', { attempted: false, reason: result.error.code });
    }
    const reconciled = await reconcile(request, input);
    return reconciled.reason === 'receipt_unavailable' && receipt ? receipt : reconciled;
  } catch {
    return reconcile(request, input);
  }
}

async function main() {
  if (process.argv.length !== 3) fail('invalid_command');
  let input = '';
  process.stdin.setEncoding('utf8');
  for await (const chunk of process.stdin) {
    input += chunk;
    if (Buffer.byteLength(input) > 8192) fail('input_too_large');
  }
  let value;
  try { value = JSON.parse(input); }
  catch { fail('invalid_json'); }
  process.stdout.write(JSON.stringify(await run(process.argv[2], value)) + '\n');
}

if (require.main === module) main().catch(error => {
  process.stderr.write(JSON.stringify({ version: VERSION, error: error instanceof RuntimeError ? error.message : 'runtime_unavailable' }) + '\n');
  process.exitCode = 1;
});

module.exports = { run, VERSION };
