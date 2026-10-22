const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {startService,MAX_TABS}=require('../session-service.cjs');
const {SessionClient}=require('../session-client.cjs');
const {opencodeSession}=require('../policy.cjs');

function fakeSpawn(){
  const calls=[];
  const spawn=(shell,args)=>{
    calls.push({shell,args});
    let output,exit;
    return {pid:777,onData:f=>output=f,onExit:f=>exit=f,write:s=>output(s),resize:()=>{},pause:()=>{},resume:()=>{},kill:()=>exit({exitCode:0})};
  };
  spawn.calls=calls;
  return spawn;
}
async function withService(run){
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'tr-oc-'));fs.chmodSync(dir,0o700);fs.writeFileSync(path.join(dir,'token'),'test-token',{mode:0o600});
  const spawn=fakeSpawn();
  const service=startService({dir,token:'test-token',spawn});
  await service.ready;
  const client=new SessionClient(dir);
  try{await run({dir,spawn,service,client});}finally{client.disconnect();await service.close();fs.rmSync(dir,{recursive:true,force:true});}
}

test('an OpenCode session keeps its identity in the terminal record',async()=>{
  await withService(async({dir,spawn,client})=>{
    const created=await client.call('create',{cwd:dir,shell:'/bin/sh',args:['--session','ses_abc123'],title:'Fix the search state',kind:'opencode',ref:'ses_abc123'});
    assert.equal(created.kind,'opencode');
    assert.equal(created.title,'Fix the search state');
    assert.equal(created.ref,'ses_abc123');
    assert.deepEqual(spawn.calls[0].args,['--session','ses_abc123']);
    const list=await client.call('list');
    assert.equal(list[0].ref,'ses_abc123');
    assert.equal(list[0].title,'Fix the search state');
  });
});

test('a shell terminal carries no OpenCode identity',async()=>{
  await withService(async({dir,client})=>{
    const created=await client.call('create',{cwd:dir,shell:'/bin/sh',args:[]});
    assert.equal(created.kind,'shell');
    assert.equal(created.ref,null);
    assert.equal(created.title,null);
  });
});

test('OpenCode session input is validated and bounded',()=>{
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'tr-ocdir-'));
  try{
    assert.throws(()=>opencodeSession(null),/Invalid OpenCode session/);
    assert.throws(()=>opencodeSession({id:'ses_ok; rm -rf /',directory:folder}),/Invalid OpenCode session id/);
    assert.throws(()=>opencodeSession({id:'ses_ok',directory:folder+'-missing'}),/no longer available/);
    assert.throws(()=>opencodeSession({id:'ses_ok',directory:__filename}),/not a folder/);
    const ok=opencodeSession({id:'ses_abc123',directory:folder,title:'  Fix   the  search  state '});
    assert.equal(ok.id,'ses_abc123');
    assert.equal(ok.title,'Fix the search state');
    assert.equal(ok.directory,fs.realpathSync(folder));
  }finally{fs.rmSync(folder,{recursive:true,force:true});}
});

test('the tab limit is enforced with a clear message',async()=>{
  await withService(async({dir,client})=>{
    for(let i=0;i<MAX_TABS;i++)await client.call('create',{cwd:dir,shell:'/bin/sh',args:[]});
    await assert.rejects(client.call('create',{cwd:dir,shell:'/bin/sh',args:[]}),/Limit of \d+ terminal tabs reached/);
    const list=await client.call('list');
    assert.equal(list.length,MAX_TABS);
  });
});
