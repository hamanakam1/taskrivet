const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {startService}=require('../session-service.cjs');
const {SessionClient}=require('../session-client.cjs');
const {spawn}=require('node:child_process');
function fakeSpawn(){let output,exit;return {pid:123,onData:f=>output=f,onExit:f=>exit=f,write:s=>output(s),resize:()=>{},pause:()=>{},resume:()=>{},kill:()=>exit({exitCode:0})};}
const wait=ms=>new Promise(r=>setTimeout(r,ms));
test('authenticated service retains process and output across client loss',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'tr-session-'));fs.chmodSync(dir,0o700);fs.writeFileSync(path.join(dir,'token'),'test-token',{mode:0o600});
 const service=startService({dir,token:'test-token',spawn:fakeSpawn});await service.ready;
 const a=new SessionClient(dir),b=new SessionClient(dir);
 try{
  const first=await a.call('create',{cwd:dir,shell:'/bin/sh',args:[]});
  await a.call('write',{id:first.id,text:'BEFORE'});await wait(40);a.disconnect();await wait(20);
  const list=await b.call('list');assert.equal(list.length,1);assert.equal(list[0].id,first.id);assert.equal(list[0].pid,123);assert.equal(list[0].state,'running');assert.equal(list[0].chunks[0].data,'BEFORE');
  assert.equal(list[0].ticketContext,null);
  await b.call('write',{id:first.id,text:'AFTER'});await wait(40);
  assert.deepEqual((await b.call('list'))[0].chunks.map(c=>c.data),['BEFORE','AFTER']);
  await assert.rejects(b.call('remove',{id:first.id}),/Stop terminal/);
  await b.call('stop',{id:first.id});assert.equal((await b.call('list'))[0].state,'exited');await b.call('remove',{id:first.id});assert.deepEqual(await b.call('list'),[]);
 }finally{a.disconnect();b.disconnect();await service.close();fs.rmSync(dir,{recursive:true,force:true});}
});
test('ticket session snapshots carry a read-only context envelope',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'tr-context-'));fs.chmodSync(dir,0o700);
 fs.writeFileSync(path.join(dir,'token'),'context-token',{mode:0o600});
 const service=startService({dir,token:'context-token',spawn:fakeSpawn});await service.ready;
 try{
  const client=new SessionClient(dir);
  const first=await client.call('create',{cwd:dir,shell:'/bin/sh',args:[],task:'SYN-1',session:'sess-1',binding:'owner'});
  const second=await client.call('create',{cwd:dir,shell:'/bin/sh',args:[],task:'SYN-1',session:'sess-1',binding:'joined'});
  assert.equal(first.ticketContext.schema,'taskrivet.ticket-context.v1');
  const snapshots=await client.call('list');
  assert.equal(snapshots.find(item=>item.id===first.id).ticketContext.session.shared_count,2);
  assert.equal(second.ticketContext.session.binding,'joined');
  assert.equal(first.ticketContext.authority.execution_authorized,false);
  assert.equal(first.ticketContext.authority.ticket_mutation,false);
  client.disconnect();await service.close();
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('registry records bounded session identity and heartbeat',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'tr-registry-'));fs.chmodSync(dir,0o700);fs.writeFileSync(path.join(dir,'token'),'registry-token',{mode:0o600});
 const service=startService({dir,token:'registry-token',spawn:fakeSpawn});await service.ready;
 try{const client=new SessionClient(dir);const first=await client.call('create',{cwd:dir,shell:'/bin/sh',args:[],task:'SYN-REG',session:'sess-reg',binding:'owner'});const registry=await client.call('registry');assert.equal(registry.version,1);assert.equal(registry.sessions[0].id,first.id);assert.equal(registry.sessions[0].task,'SYN-REG');assert.equal(registry.sessions[0].binding,'owner');assert.equal(typeof registry.sessions[0].lastHeartbeat,'number');assert.equal(fs.statSync(path.join(dir,'registry.json')).mode&0o077,0);client.disconnect();await service.close();}
 finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('unauthenticated requests cannot create processes',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'tr-auth-'));fs.chmodSync(dir,0o700);let calls=0;
 const service=startService({dir,token:'secret',spawn:()=>{calls++;return fakeSpawn();}});await service.ready;
 try{await new Promise((resolve,reject)=>{const s=net.createConnection(path.join(dir,'sessions.sock'));s.on('error',reject);s.on('connect',()=>s.write(JSON.stringify({id:1,op:'create',data:{}})+'\n'));s.on('close',resolve);});assert.equal(calls,0);}
 finally{await service.close();fs.rmSync(dir,{recursive:true,force:true});}
});
test('private directory permissions enforced',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'tr-perms-'));fs.chmodSync(dir,0o755);
 try{assert.throws(()=>startService({dir,token:'x',spawn:fakeSpawn}),/0700/);}finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('real detached Electron service keeps a shell alive after client disconnect',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'tr-real-'));fs.chmodSync(dir,0o700);fs.writeFileSync(path.join(dir,'token'),'real-test',{mode:0o600});
 const child=spawn(require('electron'),[path.resolve(__dirname,'../session-service.cjs'),dir],{env:{...process.env,ELECTRON_RUN_AS_NODE:'1'},stdio:'pipe'});
 let diagnostic='';child.stderr.on('data',d=>diagnostic+=d);const a=new SessionClient(dir),b=new SessionClient(dir);
 try{
  // Attach only: service spawning itself uses the packaged Electron runtime.
  a.token='real-test';b.token='real-test';
  for(let n=0;;n++){try{await a.attach();break;}catch(e){if(n===49)throw new Error(diagnostic||e.message);await wait(100);}}
  const t=await a.request('create',{cwd:dir,shell:'/bin/sh',args:[]});
  await a.request('write',{id:t.id,text:"printf 'PERSIST_ONE\\n'\n"});await wait(200);a.disconnect();await wait(50);
  await b.attach();const restored=(await b.request('list'))[0];assert.equal(restored.pid,t.pid);assert.equal(restored.id,t.id);assert.equal(restored.state,'running');assert.match(restored.chunks.map(c=>c.data).join(''),/PERSIST_ONE/);
  await b.request('write',{id:t.id,text:"printf 'PERSIST_TWO\\n'\n"});await wait(200);assert.match((await b.request('list'))[0].chunks.map(c=>c.data).join(''),/PERSIST_TWO/);
  await b.request('stop',{id:t.id});
 }finally{a.disconnect();b.disconnect();const exited=new Promise(r=>child.once('exit',r));child.kill();await exited;fs.rmSync(dir,{recursive:true,force:true});}
});
