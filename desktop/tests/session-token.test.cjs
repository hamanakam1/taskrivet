'use strict';

const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {readSessionToken, MAX_TOKEN_BYTES} = require('../session-token.cjs');
const {SessionClient} = require('../session-client.cjs');

function fixture(t, value = 'synthetic-token') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tr-token-'));
  fs.chmodSync(dir, 0o700);
  t.after(() => fs.rmSync(dir, {recursive: true, force: true}));
  const token = path.join(dir, 'token');
  fs.writeFileSync(token, value, {mode: 0o600});
  return {dir, token};
}

function observeDescriptor(t) {
  const open = fs.openSync;
  let fd;
  t.mock.method(fs, 'openSync', (...args) => (fd = open(...args)));
  return () => {
    assert.equal(typeof fd, 'number');
    assert.throws(() => fs.fstatSync(fd), {code: 'EBADF'});
  };
}

test('normal private token is read unchanged and its descriptor is closed', t => {
  const {token} = fixture(t);
  const closed = observeDescriptor(t);
  assert.equal(readSessionToken(token), 'synthetic-token');
  closed();
});

test('client refuses a symlink token before attempting a connection', async t => {
  const {dir, token} = fixture(t);
  const target = path.join(dir, 'target');
  fs.renameSync(token, target);
  fs.symlinkSync(target, token);
  const client = new SessionClient(dir);
  const attach = t.mock.method(client, 'attach', async () => assert.fail('must not attach'));
  await assert.rejects(client.connect(), {code: 'ELOOP'});
  assert.equal(attach.mock.callCount(), 0);
  assert.equal(client.token, undefined);
});

test('path replacement after validation cannot redirect the token read', t => {
  const {dir, token} = fixture(t);
  const replacement = path.join(dir, 'replacement');
  fs.writeFileSync(replacement, 'different-content', {mode: 0o600});
  const stat = fs.fstatSync;
  const hook = t.mock.method(fs, 'fstatSync', fd => {
    const result = stat(fd);
    hook.mock.restore();
    fs.renameSync(token, path.join(dir, 'original'));
    fs.symlinkSync(replacement, token);
    return result;
  });
  const closed = observeDescriptor(t);
  assert.equal(readSessionToken(token), 'synthetic-token');
  closed();
  assert.throws(() => readSessionToken(token), {code: 'ELOOP'});
});

test('directory and unsafe file permissions are refused with descriptors closed', t => {
  const {dir, token} = fixture(t);
  const closed = observeDescriptor(t);
  assert.throws(() => readSessionToken(dir), /Unsafe session token/);
  closed();
  for (const mode of [0o644, 0o640, 0o606]) {
    fs.chmodSync(token, mode);
    assert.throws(() => readSessionToken(token), /Unsafe session token/);
    closed();
  }
});

test('foreign ownership is refused using the opened file metadata', t => {
  const {token} = fixture(t);
  const stat = fs.fstatSync;
  const closed = observeDescriptor(t);
  const hook = t.mock.method(fs, 'fstatSync', fd => {
    const result = stat(fd);
    result.uid = process.getuid() + 1;
    return result;
  });
  assert.throws(() => readSessionToken(token), /Unsafe session token/);
  hook.mock.restore();
  closed();
});

test('FIFO token is refused promptly instead of blocking open', t => {
  const {dir} = fixture(t);
  const fifo = path.join(dir, 'fifo');
  const made = spawnSync('mkfifo', ['-m', '600', fifo], {encoding: 'utf8'});
  assert.equal(made.status, 0, made.stderr);
  const script = `const {readSessionToken}=require(process.argv[1]);
    try { readSessionToken(process.argv[2]); process.exit(2); }
    catch (error) { if (error.message !== 'Unsafe session token') throw error; }`;
  const child = spawnSync(process.execPath, ['-e', script, require.resolve('../session-token.cjs'), fifo],
    {encoding: 'utf8', timeout: 3000});
  assert.equal(child.error, undefined);
  assert.equal(child.status, 0, child.stderr);
});

test('empty and oversized tokens are refused and exact bound is supported', t => {
  const {token} = fixture(t, 'x'.repeat(MAX_TOKEN_BYTES));
  const closed = observeDescriptor(t);
  assert.equal(readSessionToken(token).length, MAX_TOKEN_BYTES);
  closed();
  for (const value of ['', 'x'.repeat(MAX_TOKEN_BYTES + 1)]) {
    fs.writeFileSync(token, value);
    assert.throws(() => readSessionToken(token), /Unsafe session token/);
    closed();
  }
});

test('growth after fstat is bounded and refused', t => {
  const {token} = fixture(t);
  const stat = fs.fstatSync;
  const closed = observeDescriptor(t);
  const hook = t.mock.method(fs, 'fstatSync', fd => {
    const result = stat(fd);
    hook.mock.restore();
    fs.appendFileSync(token, 'x'.repeat(MAX_TOKEN_BYTES));
    return result;
  });
  assert.throws(() => readSessionToken(token), /Unsafe session token/);
  closed();
});

test('short reads are accumulated without truncating the token', t => {
  const {token} = fixture(t);
  const read = fs.readSync;
  t.mock.method(fs, 'readSync', (fd, buffer, offset, length, position) =>
    read(fd, buffer, offset, Math.min(length, 2), position));
  assert.equal(readSessionToken(token), 'synthetic-token');
});

test('metadata and read errors still close the opened descriptor', t => {
  const {token} = fixture(t);
  const closed = observeDescriptor(t);
  for (const method of ['fstatSync', 'readSync']) {
    const hook = t.mock.method(fs, method, () => { throw new Error('synthetic I/O failure'); });
    assert.throws(() => readSessionToken(token), /synthetic I\/O failure/);
    hook.mock.restore();
    closed();
  }
});
