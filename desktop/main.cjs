'use strict';
const {app, BrowserWindow, ipcMain, dialog, Menu} = require('electron');
const {execFile} = require('node:child_process');
const {promisify} = require('node:util');
const {createHash} = require('node:crypto');
const path = require('node:path');
const os = require('node:os');
const fs = require('node:fs');
const {pathToFileURL} = require('node:url');
const {SessionClient} = require('./session-client.cjs');
const policy = require('./policy.cjs');
const exec = promisify(execFile);

const page = pathToFileURL(path.join(__dirname, 'ui/index.html')).href;
let win, python;
const coreRoot = app.isPackaged ? path.join(process.resourcesPath, 'core') : path.resolve(__dirname, '..');
const db = process.env.TASKRIVET_DB || path.join(os.homedir(), '.taskrivet', 'ledger.sqlite');
const runtime=path.join(os.homedir(), '.taskrivet', 'sessions-'+createHash('sha256').update(path.resolve(db)).digest('hex').slice(0,12));
const sessions=new SessionClient(runtime);
for(const kind of ['terminal:data','terminal:exit'])sessions.on(kind,payload=>notify(kind,payload));
sessions.on('disconnected',()=>notify('terminal:disconnected',{}));
async function findPython() {
  for (const candidate of ['/opt/homebrew/bin/python3', '/usr/local/bin/python3', '/usr/bin/python3', 'python3']) {
    try {
      await exec(candidate, ['-c', 'import sys; assert sys.version_info >= (3,11)'], {timeout: 5000});
      return candidate;
    } catch {}
  }
  throw new Error('Python 3.11+ is required for the coordination ledger. Terminals are still available.');
}
async function ledger(args) {
  python ||= await findPython();
  try {
    const {stdout} = await exec(python, ['-m','taskrivet','--db', db, ...args], {
      cwd: coreRoot, env: {...process.env, PYTHONPATH: coreRoot}, timeout: 15000, maxBuffer: 2 * 1024 * 1024
    });
    return JSON.parse(stdout);
  } catch (e) {
    let message = e.message;
    try { message = JSON.parse(e.stderr).error; } catch {}
    throw new Error(message);
  }
}
function trusted(event) {
  if (!win || event.sender !== win.webContents || event.senderFrame !== win.webContents.mainFrame || event.senderFrame.url !== page) throw new Error('Untrusted caller');
}
function handle(name, fn) { ipcMain.handle(name, async (event, ...args) => { trusted(event); return fn(...args); }); }
function notify(kind, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(kind, payload);
}
async function newTerminal({cwd, task = null, tool = null, opencode = null, session = null} = {}) {
  await sessions.connect();
  let executable = null, args = [], title = null, kind = 'shell', ref = null;
  if (opencode) {
    const target = policy.opencodeSession(opencode);
    executable = await opencodeBinary();
    if (!executable) throw new Error('OpenCode is not installed in a scanned location. Refresh the tool catalog.');
    args = ['--session', target.id];
    cwd = target.directory;
    title = target.title || target.id;
    kind = 'opencode';
    ref = target.id;
  } else {
    cwd = policy.directory(cwd || os.homedir());
    if (tool) {
      policy.text(tool, 'tool', 128);
      const catalog = await ledger(['tools']);
      executable = catalog.tools.find(t => t.id === tool && t.installed)?.executable;
      if (!executable) throw new Error('Tool is no longer installed. Refresh the catalog.');
    }
  }
  let ledgerSession = null;
  let binding = null;
  if (session) {
    // A second pane may join an existing attempt. It never claims a new lease.
    policy.text(session, 'session', 128);
    if (!task) throw new Error('A shared pane must name its task.');
    policy.text(task, 'task');
    ledgerSession = policy.sharedSession(await ledger(['detail', '--task', task, '--session', session]), session);
    binding = 'joined';
  } else if (task) {
    policy.text(task, 'task');
    ledgerSession = (await ledger(['start', task, '--owner', 'desktop-terminal'])).session_id;
    binding = 'owner';
  }
  const shell = executable || (process.platform === 'darwin' ? '/bin/zsh' : '/bin/bash');
  const launchArgs = args.length ? args : (executable ? [] : ['-l']);
  try {
    return await sessions.call('create', {cwd, task, session: ledgerSession, binding, shell, args: launchArgs, title, kind, ref, db});
  } catch (e) {
    if (ledgerSession && !session) await ledger(['fail', ledgerSession, '--category','terminal_start','--summary',String(e.message)]).catch(()=>{});
    throw e;
  }
}
function configuredRepo(){try{return JSON.parse(fs.readFileSync(path.join(os.homedir(),'.taskrivet','github-bridge.json'),'utf8')).repo||'';}catch{return '';}}
let opencodePath=null;
async function opencodeBinary(){
  if(opencodePath)return opencodePath;
  const catalog=await ledger(['tools']);
  opencodePath=catalog.tools.find(t=>t.id==='opencode'&&t.installed)?.executable||null;
  return opencodePath;
}
handle('bootstrap', async () => ({home:os.homedir(), terminals:await sessions.call('list'), version:app.getVersion(),githubRepo:configuredRepo()}));
handle('opencode:sessions', async (options = {}) => {
  const limit = Math.max(1, Math.min(Number(options.limit) || 60, 200));
  const args = ['opencode-sessions', '--limit', String(limit)];
  if (options.project) args.push('--project', policy.text(String(options.project), 'project', 4096));
  return ledger(args);
});
handle('ledger', async (action, data) => {
  if (['accept','retry','cancel','finish'].includes(action)) {
    const active = (await sessions.call('list')).some(t => t.state==='running' && (t.task===data?.task || t.session===data?.session));
    if (active) throw new Error('Stop the linked terminal before this lifecycle decision.');
  }
  return ledger(policy.ledgerArgs(action, data));
});
handle('choose-directory', async () => {
  const result = await dialog.showOpenDialog(win, {properties:['openDirectory']});
  return result.canceled ? null : result.filePaths[0];
});
handle('terminal:create', newTerminal);
handle('terminal:write', (id, data) => sessions.call('write',{id,text:data}));
handle('terminal:resize', (id, cols, rows) => sessions.call('resize',{id,cols,rows}));
handle('terminal:stop', async id => {
  const {response}=await dialog.showMessageBox(win, {type:'warning', message:'Stop this terminal?', detail:'This interrupts its process. Detached children may need separate reconciliation.', buttons:['Keep running','Stop terminal'], defaultId:0, cancelId:0});
  if(response!==1)return false;
  return sessions.call('stop',{id});
});
handle('terminal:remove', id => sessions.call('remove',{id}));
function createWindow() {
  win=new BrowserWindow({width:1400,height:920,minWidth:1050,minHeight:720,title:'Taskrivet',backgroundColor:'#10191e',titleBarStyle:'hiddenInset',
    webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true,webSecurity:true}});
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.webContents.on('will-navigate',e=>e.preventDefault());
  win.webContents.session.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false));
  win.webContents.session.setPermissionCheckHandler(()=>false);
  win.webContents.session.webRequest.onBeforeRequest((details,cb)=>cb({cancel:!details.url.startsWith('file://')}));
  win.loadURL(page);
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance',()=>{if(win){win.show();win.focus();}});
  app.whenReady().then(()=>{
    const bridgeConfig=path.join(os.homedir(),'.taskrivet','github-bridge.json');
    let githubBusy=false;
    async function syncGitHub(){
      if(githubBusy||!fs.existsSync(bridgeConfig))return;githubBusy=true;
      try{
        python ||= await findPython();
        const {stdout}=await exec(python,['-m','taskrivet','github-cycle','--config',bridgeConfig],{cwd:coreRoot,env:{...process.env,PYTHONPATH:coreRoot},timeout:180000,maxBuffer:2*1024*1024});
        const receipt=JSON.parse(stdout);
        if(receipt.state==='dashboard_reconciliation_failed'||Object.values(receipt.poll?.coverage||{}).some(feed=>feed.error))throw new Error('Incomplete reconciliation');
      }
      catch(e){notify('integration:error',{message:'GitHub sync incomplete; inspect integration receipts before relying on freshness.'});}
      finally{githubBusy=false;}
    }
    syncGitHub();const githubTimer=setInterval(syncGitHub,300000);app.on('before-quit',()=>clearInterval(githubTimer));
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      {label:'Taskrivet',submenu:[{role:'about'},{type:'separator'},{role:'hide'},{role:'hideOthers'},{role:'unhide'},{type:'separator'},{role:'quit'}]},
      {role:'editMenu'}, {label:'Window',submenu:[{role:'minimize'},{role:'zoom'},{role:'close'},{label:'Show workspace',click:()=>{win.show();win.focus();}}]}
    ]));
    createWindow();
  });
  app.on('activate',()=>{if(!win || win.isDestroyed())createWindow();else win.show();});
  app.on('window-all-closed',()=>{if(process.platform!=='darwin')app.quit();});
  app.on('before-quit',()=>sessions.disconnect());
}
