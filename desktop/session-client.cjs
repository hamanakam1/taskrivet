'use strict';
const net=require('node:net'),fs=require('node:fs'),path=require('node:path');
const {spawn}=require('node:child_process');
const {randomBytes}=require('node:crypto');
const {EventEmitter}=require('node:events');
// Keep native PTY imports in the service, not the client.
const VERSION=1,MAX_FRAME=32*1024*1024;
function privateDirectory(dir){fs.mkdirSync(dir,{recursive:true,mode:0o700});const st=fs.lstatSync(dir);if(!st.isDirectory()||st.isSymbolicLink()||st.uid!==process.getuid()||(st.mode&0o077))throw new Error('Session directory requires mode 0700 and current-user ownership');}
class SessionClient extends EventEmitter{
 constructor(dir){super();this.dir=dir;this.pending=new Map();this.next=0;this.socket=null;this.connecting=null;}
 async connect(){
  if(this.socket&&!this.socket.destroyed)return;
  if(this.connecting)return this.connecting;
  this.connecting=this.open();try{await this.connecting;}finally{this.connecting=null;}
 }
 async open(){
  privateDirectory(this.dir);
  const tokenPath=path.join(this.dir,'token');
  try{fs.writeFileSync(tokenPath,randomBytes(32).toString('hex'),{flag:'wx',mode:0o600});}catch(e){if(e.code!=='EEXIST')throw e;}
  const st=fs.lstatSync(tokenPath);
  if(!st.isFile()||st.isSymbolicLink()||st.uid!==process.getuid()||(st.mode&0o077))throw new Error('Unsafe session token');
  this.token=fs.readFileSync(tokenPath,'utf8');
  try{await this.attach();return;}catch(e){if(!['ENOENT','ECONNREFUSED'].includes(e.code))throw e;}
  const lock=path.join(this.dir,'starting');
  let owner=false;
  try{fs.mkdirSync(lock,{mode:0o700});owner=true;}catch(e){if(e.code!=='EEXIST')throw e;}
  if(owner){
   try{
    // Recheck after acquiring the startup lock. Never unlink a live socket.
    try{await this.attach();return;}catch(e){if(!['ENOENT','ECONNREFUSED'].includes(e.code))throw e;}
    const sock=path.join(this.dir,'sessions.sock');
    try{const s=fs.lstatSync(sock);if(!s.isSocket()||s.uid!==process.getuid())throw new Error('Unsafe session socket');fs.unlinkSync(sock);}catch(e){if(e.code!=='ENOENT')throw e;}
    const child=spawn(process.execPath,[path.join(__dirname,'session-service.cjs'),this.dir],{detached:true,stdio:'ignore',env:{...process.env,ELECTRON_RUN_AS_NODE:'1'}});
    child.on('error',()=>{});child.unref();
    await this.waitForService();
   }finally{fs.rmdirSync(lock);}
  }else await this.waitForService();
 }
 async waitForService(){for(let i=0;i<50;i++){try{await this.attach();return;}catch(e){if(!['ENOENT','ECONNREFUSED'].includes(e.code))throw e;}await new Promise(r=>setTimeout(r,100));}throw new Error('Session service unavailable. A stale startup lock may require operator reconciliation. Existing commands were not replayed.');}
 attach(){return new Promise((resolve,reject)=>{
  const socket=net.createConnection(path.join(this.dir,'sessions.sock'));let buffer='',connected=false;
  socket.setEncoding('utf8');
  socket.once('error',reject);
  socket.on('error',()=>{});
  socket.on('data',chunk=>{buffer+=chunk;if(Buffer.byteLength(buffer)>MAX_FRAME){socket.destroy();return;}let end;while((end=buffer.indexOf('\n'))>=0){const raw=buffer.slice(0,end);buffer=buffer.slice(end+1);let m;try{m=JSON.parse(raw);}catch{socket.destroy();return;}if(m.event)this.emit(m.event,m.payload);else{const p=this.pending.get(m.id);if(p){this.pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(new Error(m.error)):p.resolve(m.result);}}}});
  socket.on('close',()=>{if(this.socket===socket){this.socket=null;for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(new Error('Session connection lost; command outcome unknown. Reconnect before retrying.'));}this.pending.clear();if(connected)this.emit('disconnected');}});
  socket.on('connect',async()=>{this.socket=socket;try{await this.request('hello',{},{token:this.token,version:VERSION});connected=true;resolve();}catch(e){socket.destroy();reject(e);}});
 });}
 request(op,data={},extra={}){return new Promise((resolve,reject)=>{if(!this.socket||this.socket.destroyed){reject(new Error('Session service disconnected'));return;}const id=++this.next;const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error('Session request timed out; outcome unknown, do not blindly retry.'));},10000);this.pending.set(id,{resolve,reject,timer});this.socket.write(JSON.stringify({id,op,data,...extra})+'\n');});}
 async call(op,data){await this.connect();return this.request(op,data);}
 disconnect(){this.socket?.destroy();}
}
module.exports={SessionClient};
