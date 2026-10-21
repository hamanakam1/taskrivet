'use strict';
const fs = require('node:fs');
function text(value, label, max = 16000) {
  if (typeof value !== 'string' || !value.trim() || value.length > max || value.includes('\0')) throw new Error(`Invalid ${label}`);
  return value;
}
function dimensions(cols, rows) {
  if (!Number.isInteger(cols) || !Number.isInteger(rows) || cols < 2 || cols > 500 || rows < 1 || rows > 300) throw new Error('Invalid terminal dimensions');
  return {cols, rows};
}
function directory(value) {
  text(value, 'working directory', 4096);
  const resolved = fs.realpathSync(value);
  if (!fs.statSync(resolved).isDirectory()) throw new Error('Working directory is not a folder');
  return resolved;
}
function ledgerArgs(action, data = {}) {
  const t = (key, max) => text(data[key], key, max);
  switch (action) {
    case 'dashboard': {
      if(!Number.isInteger(data.offset)||data.offset<0||data.offset>1000000)throw new Error('Invalid offset');
      return ['dashboard-preview','--url',t('url',256),'--status',t('status',32),'--offset',String(data.offset)];
    }
    case 'tools': return data.history === true ? ['tools', '--history'] : ['tools'];
    case 'status': return ['status'];
    case 'pack': return ['pack', t('task'), '--max-bytes', '12000'];
    case 'create': return ['task-add', t('id', 128), '--objective', t('objective'), '--acceptance', t('acceptance'), '--scope', t('scope')];
    case 'checkpoint': {
      if (!Number.isSafeInteger(data.tokens) || data.tokens < 0) throw new Error('Tokens must be a cumulative nonnegative integer');
      return ['checkpoint', t('session'), '--summary', t('summary'), '--evidence', t('evidence'), '--next', t('next'), '--tokens', String(data.tokens)];
    }
    case 'fail': return ['fail', t('session'), '--category', t('category', 128), '--summary', t('summary')];
    case 'finish': return ['finish', t('session'), '--evidence', t('evidence')];
    case 'accept': case 'retry': case 'cancel': return [action, t('task'), '--reason', t('reason')];
    default: throw new Error('Unsupported ledger operation');
  }
}
module.exports = {text, dimensions, directory, ledgerArgs};
