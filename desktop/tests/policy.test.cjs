const {test}=require('node:test');
const assert=require('node:assert/strict');
const {ledgerArgs,dimensions,directory,text}=require('../policy.cjs');
test('IPC exposes only explicit ledger operations',()=>{
  assert.throws(()=>ledgerArgs('shell',{command:'anything'}));
  assert.deepEqual(ledgerArgs('status'),['status']);
  assert.throws(()=>ledgerArgs('bosun',{}));
  assert.deepEqual(ledgerArgs('tools',{history:true}),['tools','--history']);
});
test('arguments preserve literal shell characters without shell evaluation',()=>{
  assert.deepEqual(ledgerArgs('pack',{task:'a; touch x'}),['pack','a; touch x','--max-bytes','12000']);
});
test('terminal size and input limits are enforced',()=>{
  assert.throws(()=>dimensions(0,10));assert.throws(()=>dimensions(80,10000));
  assert.throws(()=>text('a\0b','input'));assert.throws(()=>text('x'.repeat(100),'input',10));
  assert.deepEqual(dimensions(80,24),{cols:80,rows:24});
});
test('usage cannot be negative or noninteger',()=>{
  assert.throws(()=>ledgerArgs('checkpoint',{tokens:-1}));
  assert.throws(()=>ledgerArgs('checkpoint',{tokens:1.5}));
});
test('directory must exist and be a directory',()=>{
  assert.throws(()=>directory(__filename));assert.equal(directory(__dirname),__dirname);
});
