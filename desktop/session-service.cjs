'use strict';
// A single local service owns PTYs. Desktop clients may disconnect freely.
const net=require('node:net'), fs=require('node:fs'), path=require('node:path');
const {randomUUID}=require('node:crypto');
const pty=require('node-pty');
const policy=require('./policy.cjs');
const VERSION=1, MAX_FRAME=32*1024*1024, MAX_TABS=24;
function privateDirectory(dir){
  fs.mkdirSync(dir,{recursive:true,mode:0o700});
  const st=fs.lstatSync(dir);
  if(!st.isDirectory()||st.isSymbolicLink()||st.uid!==process.getuid()||(st.mode&0o077))throw new Error('Session directory must be owned by you with mode 0700');
}
function startService({dir,token,spawn=pty.spawn}){
  privateDirectory(dir);
  const socketPath=path.join(dir,'sessions.sock'), registryPath=path.join(dir,'registry.json'), sessions=new Map(), clients=new Set();
  function writeRegistry(){
    const rows=[...sessions.values()].map(t=>({id:t.id,task:t.task,session:t.session,binding:t.binding||'standalone',state:t.state,pid:t.proc.pid,cwd:t.cwd,createdAt:t.createdAt,lastHeartbeat:t.lastHeartbeat,updatedAt:Date.now()}));
    const tmp=registryPath+'.tmp';fs.writeFileSync(tmp,JSON.stringify({version:1,updatedAt:Date.now(),sessions:rows})+'\n',{mode:0o600});fs.renameSync(tmp,registryPath);
  }
  function snapshot(t){
    t.lastHeartbeat=Date.now();
    const sharedCount=t.session?[...sessions.values()].filter(item=>item.session===t.session).length:0;
    return {id:t.id,cwd:t.cwd,task:t.task,session:t.session,binding:t.binding||null,
      ticketContext:t.task?{schema:'taskrivet.ticket-context.v1',ticket:{key:t.task},
        session:{id:t.session||null,binding:t.binding||'standalone',shared_count:sharedCount},
        authority:{context_readonly:true,ticket_mutation:false,acceptance:false,execution_authorized:false},
      provenance:{source:'taskrivet desktop session service'}}:null,
      shell:t.shell,state:t.state,exitCode:t.exitCode,chunks:t.chunks,pid:t.proc.pid,title:t.title,kind:t.kind,ref:t.ref,
      createdAt:t.createdAt,lastHeartbeat:t.lastHeartbeat};
  }
  function send(c,message){
    if(c.destroyed)return;
    if(c.writableLength>MAX_FRAME){c.destroy();return;}
    c.write(JSON.stringify(message)+'\n');
  }
  function event(kind,payload){for(const c of clients)send(c,{event:kind,payload});}
  function record(id){const t=sessions.get(id);if(!t)throw new Error('Unknown terminal; no command was replayed');return t;}
  function dispatch(op,data={}){
    if(op==='list'){const rows=[...sessions.values()].map(snapshot);writeRegistry();return rows;}
    if(op==='registry'){try{return JSON.parse(fs.readFileSync(registryPath,'utf8'));}catch{return {version:1,updatedAt:null,sessions:[]};}}
    if(op==='create'){
      if(sessions.size>=MAX_TABS)throw new Error('Limit of '+MAX_TABS+' terminal tabs reached');
      const cwd=policy.directory(data.cwd), shell=policy.text(data.shell,'executable',4096);
      if(!path.isAbsolute(shell))throw new Error('Executable must be absolute');
      if(!Array.isArray(data.args)||data.args.length>64||data.args.some(x=>typeof x!=='string'||x.includes('\0')||x.length>65536))throw new Error('Invalid arguments');
      for(const key of ['task','session'])if(data[key]!=null)policy.text(data[key],key,128);
      for(const key of ['title','kind','ref','binding'])if(data[key]!=null)policy.text(data[key],key,256);
      const proc=spawn(shell,data.args,{name:'xterm-256color',cols:100,rows:30,cwd,
        env:{...process.env,ELECTRON_RUN_AS_NODE:undefined,TERM:'xterm-256color',COLORTERM:'truecolor',TASKRIVET_DB:data.db}});
      const t={id:randomUUID(),proc,cwd,shell,task:data.task||null,session:data.session||null,binding:data.binding||null,state:'running',chunks:[],seq:0,bytes:0,pending:'',paused:false,createdAt:Date.now(),lastHeartbeat:Date.now(),
        title:data.title||null,kind:data.kind||'shell',ref:data.ref||null};
      sessions.set(t.id,t);
      writeRegistry();
      function flush(){
        if(!t.pending)return;
        const text=t.pending.slice(0,65536);t.pending=t.pending.slice(text.length);
        const chunk={seq:++t.seq,data:text};t.chunks.push(chunk);t.bytes+=Buffer.byteLength(text);
        while(t.bytes>1024*1024&&t.chunks.length>1)t.bytes-=Buffer.byteLength(t.chunks.shift().data);
        event('terminal:data',{id:t.id,...chunk});
        if(t.paused&&t.pending.length<65536){proc.resume();t.paused=false;}
      }
      t.timer=setInterval(flush,16);
      proc.onData(text=>{t.pending+=text;if(t.pending.length>262144&&!t.paused){proc.pause();t.paused=true;}});
      proc.onExit(({exitCode})=>{clearInterval(t.timer);while(t.pending)flush();t.state='exited';t.exitCode=exitCode;t.lastHeartbeat=Date.now();writeRegistry();event('terminal:exit',{id:t.id,exitCode});});
      return snapshot(t);
    }
    const t=record(data.id);
    if(op==='write'){
      if(t.state!=='running')throw new Error('Terminal has exited');
      if(typeof data.text!=='string'||data.text.length>65536)throw new Error('Invalid input');
      t.proc.write(data.text);return true;
    }
    if(op==='resize'){policy.dimensions(data.cols,data.rows);if(t.state==='running')t.proc.resize(data.cols,data.rows);return true;}
    if(op==='stop'){if(t.state==='running')t.proc.kill();return true;}
    if(op==='remove'){if(t.state==='running')throw new Error('Stop terminal before closing its tab');sessions.delete(t.id);writeRegistry();return true;}
    throw new Error('Unsupported session operation');
  }
  const server=net.createServer(c=>{
    let buffer='',authenticated=false;
    const timeout=setTimeout(()=>{if(!authenticated)c.destroy();},3000);
    c.on('error',()=>{});
    c.on('close',()=>{clearTimeout(timeout);clients.delete(c);});
    c.on('data',chunk=>{
      buffer+=chunk.toString('utf8');if(Buffer.byteLength(buffer)>MAX_FRAME){c.destroy();return;}
      let end;
      while((end=buffer.indexOf('\n'))>=0){
        const raw=buffer.slice(0,end);buffer=buffer.slice(end+1);
        let request;
        try{
          request=JSON.parse(raw);
          if(!authenticated){
            if(request.op!=='hello'||request.token!==token||request.version!==VERSION){c.destroy();return;}
            authenticated=true;clearTimeout(timeout);clients.add(c);send(c,{id:request.id,result:{version:VERSION,pid:process.pid}});continue;
          }
          send(c,{id:request.id,result:dispatch(request.op,request.data)});
        }catch(e){send(c,{id:request?.id,error:e.message});}
      }
    });
    c.setEncoding('utf8');
  });
  server.on('error',()=>{});
  const ready=new Promise((resolve,reject)=>{server.once('error',reject);server.listen(socketPath,()=>{fs.chmodSync(socketPath,0o600);resolve();});});
  async function close(){for(const t of sessions.values()){clearInterval(t.timer);if(t.state==='running')t.proc.kill();}for(const c of clients)c.destroy();await new Promise(resolve=>server.close(resolve));}
  return {ready,close,server,sessions};
}
module.exports={startService,privateDirectory,VERSION,MAX_FRAME,MAX_TABS};
if(require.main===module){
  const dir=process.argv[2];
  try{
    privateDirectory(dir);
    const tokenPath=path.join(dir,'token'),st=fs.lstatSync(tokenPath);
    if(!st.isFile()||st.isSymbolicLink()||st.uid!==process.getuid()||(st.mode&0o077))throw new Error('Unsafe token file');
    const service=startService({dir,token:fs.readFileSync(tokenPath,'utf8')});
    service.ready.catch(()=>process.exit(1));
    for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>service.close().finally(()=>process.exit(0)));
  }catch{process.exit(1);}
}
