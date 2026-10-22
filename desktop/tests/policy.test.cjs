const {test}=require('node:test');
const assert=require('node:assert/strict');
const {ledgerArgs,dimensions,directory,text,sharedSession}=require('../policy.cjs');
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

test('dashboard bridge exposes only bounded preview arguments',()=>{
 assert.deepEqual(ledgerArgs('dashboard',{url:'http://127.0.0.1:8080',status:'planned',offset:100}),['dashboard-preview','--url','http://127.0.0.1:8080','--status','planned','--offset','100']);
 assert.throws(()=>ledgerArgs('dashboard',{offset:-1}));
});

test('the session detail read is bounded to one task and optional session',()=>{
 assert.deepEqual(ledgerArgs('detail',{task:'search'}),['detail','--task','search']);
 assert.deepEqual(ledgerArgs('detail',{task:'search',session:'abc123'}),['detail','--task','search','--session','abc123']);
 assert.throws(()=>ledgerArgs('detail',{}));
 assert.throws(()=>ledgerArgs('detail',{task:''}));
 assert.throws(()=>ledgerArgs('detail',{task:'a',session:'\0'}));
});

test('a shared pane may only join a live session of its own task',()=>{
 const live={session:{id:'abc123',status:'active'}};
 assert.equal(sharedSession(live,'abc123'),'abc123');
 assert.throws(()=>sharedSession(live,'other'),/does not belong/);
 assert.throws(()=>sharedSession({session:{id:'abc123',status:'expired'}},'abc123'),/no longer active/);
 assert.throws(()=>sharedSession(null,'abc123'));
 assert.throws(()=>sharedSession(live,'\0'));
});
