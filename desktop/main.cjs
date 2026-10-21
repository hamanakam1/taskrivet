'use strict';
const {app, BrowserWindow, ipcMain, dialog, Menu} = require('electron');
const {execFile} = require('node:child_process');
const {promisify} = require('node:util');
const {randomUUID} = require('node:crypto');
const path = require('node:path');
const os = require('node:os');
const fs = require('node:fs');
const {pathToFileURL} = require('node:url');
const pty = require('node-pty');
const policy = require('./policy.cjs');
const exec = promisify(execFile);
const terminals = new Map();
const page = pathToFileURL(path.join(__dirname, 'ui/index.html')).href;
let win, python, quitting = false, quitPrompt = false;
const coreRoot = app.isPackaged ? path.join(process.resourcesPath, 'core') : path.resolve(__dirname, '..');
const db = process.env.TASKRIVET_DB || path.join(os.homedir(), '.taskrivet', 'ledger.sqlite');
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
function record(id) {
  const item = terminals.get(id);
  if (!item) throw new Error('Unknown terminal');
  return item;
}
function summary(item) {
  return {id:item.id, cwd:item.cwd, task:item.task, session:item.session, state:item.state, exitCode:item.exitCode, chunks:item.chunks, shell:item.shell};
}
function notify(kind, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(kind, payload);
}
async function newTerminal({cwd, task = null, tool = null} = {}) {
  if (terminals.size >= 12) throw new Error('Limit of 12 terminal tabs reached. Close a stopped tab first.');
  cwd = policy.directory(cwd || os.homedir());
  let executable = null;
  if (tool) {
    policy.text(tool, 'tool', 128);
    const catalog = await ledger(['tools']);
    executable = catalog.tools.find(t => t.id === tool && t.installed)?.executable;
    if (!executable) throw new Error('Tool is no longer installed. Refresh the catalog.');
  }
  let session = null;
  if (task) {
    policy.text(task, 'task');
    session = (await ledger(['start', task, '--owner', 'desktop-terminal'])).session_id;
  }
  const id = randomUUID();
  const shell = executable || (process.platform === 'darwin' ? '/bin/zsh' : '/bin/bash');
  try {
    const proc = pty.spawn(shell, executable ? [] : ['-l'], {name:'xterm-256color', cols:100, rows:30, cwd,
      env:{...process.env, TERM:'xterm-256color', COLORTERM:'truecolor', TASKRIVET_DB:db}});
    const item = {id, proc, cwd, task, session, shell, state:'running', chunks:[], seq:0, bytes:0, pending:'', paused:false};
    terminals.set(id, item);
    const flush = () => {
      if (!item.pending) return;
      const data = item.pending.slice(0, 65536);
      item.pending = item.pending.slice(data.length);
      const chunk = {seq:++item.seq, data};
      item.chunks.push(chunk); item.bytes += data.length;
      while (item.bytes > 1024*1024 && item.chunks.length > 1) item.bytes -= item.chunks.shift().data.length;
      notify('terminal:data', {id, ...chunk});
      if (item.paused && item.pending.length < 65536) { item.proc.resume(); item.paused = false; }
    };
    item.timer = setInterval(flush, 16);
    proc.onData(data => {
      item.pending += data;
      if (item.pending.length > 262144 && !item.paused) { proc.pause(); item.paused = true; }
    });
    proc.onExit(({exitCode}) => {
      clearInterval(item.timer);
      while (item.pending) flush();
      item.state='exited'; item.exitCode=exitCode;
      notify('terminal:exit', {id, exitCode});
      // Shell exit is not evidence that a task succeeded or failed.
    });
    return summary(item);
  } catch (e) {
    if (session) await ledger(['fail', session, '--category','terminal_start','--summary',String(e.message)]).catch(()=>{});
    throw e;
  }
}
handle('bootstrap', () => ({home:os.homedir(), terminals:[...terminals.values()].map(summary), version:app.getVersion()}));
handle('ledger', async (action, data) => {
  if (['accept','retry','cancel','finish'].includes(action)) {
    const active = [...terminals.values()].some(t => t.state==='running' && (t.task===data?.task || t.session===data?.session));
    if (active) throw new Error('Stop the linked terminal before this lifecycle decision.');
  }
  return ledger(policy.ledgerArgs(action, data));
});
handle('choose-directory', async () => {
  const result = await dialog.showOpenDialog(win, {properties:['openDirectory']});
  return result.canceled ? null : result.filePaths[0];
});
handle('terminal:create', newTerminal);
handle('terminal:write', (id, data) => {
  const item = record(id);
  if (item.state !== 'running') throw new Error('Terminal has exited');
  if (typeof data !== 'string' || data.length > 65536) throw new Error('Input is too large');
  item.proc.write(data);
});
handle('terminal:resize', (id, cols, rows) => {
  policy.dimensions(cols, rows); const item = record(id);
  if (item.state === 'running') item.proc.resize(cols, rows);
});
handle('terminal:stop', async id => {
  const item=record(id);
  if (item.state !== 'running') return true;
  const {response}=await dialog.showMessageBox(win, {type:'warning', message:'Stop this terminal?', detail:'This closes its shell and may interrupt commands. Detached processes may remain; reconcile them before retrying the task.', buttons:['Keep running','Stop terminal'], defaultId:0, cancelId:0});
  if (response !== 1) return false;
  item.proc.kill(); return true;
});
handle('terminal:remove', id => {
  const item=record(id);
  if (item.state==='running') throw new Error('Stop the terminal before closing its tab');
  terminals.delete(id);
});
function createWindow() {
  win=new BrowserWindow({width:1400,height:920,minWidth:1050,minHeight:720,title:'Taskrivet',backgroundColor:'#10191e',titleBarStyle:'hiddenInset',
    webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true,webSecurity:true}});
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.webContents.on('will-navigate',e=>e.preventDefault());
  win.webContents.session.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false));
  win.webContents.session.setPermissionCheckHandler(()=>false);
  win.webContents.session.webRequest.onBeforeRequest((details,cb)=>cb({cancel:!details.url.startsWith('file://')}));
  win.on('close', e => {
    if (!quitting && [...terminals.values()].some(t=>t.state==='running')) { e.preventDefault(); win.hide(); }
  });
  win.loadURL(page);
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance',()=>{if(win){win.show();win.focus();}});
  app.whenReady().then(()=>{
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      {label:'Taskrivet',submenu:[{role:'about'},{type:'separator'},{role:'hide'},{role:'hideOthers'},{role:'unhide'},{type:'separator'},{role:'quit'}]},
      {role:'editMenu'}, {label:'Window',submenu:[{role:'minimize'},{role:'zoom'},{role:'close'},{label:'Show workspace',click:()=>{win.show();win.focus();}}]}
    ]));
    createWindow();
  });
  app.on('activate',()=>{if(!win || win.isDestroyed())createWindow();else win.show();});
  app.on('window-all-closed',()=>{if(process.platform!=='darwin')app.quit();});
  app.on('before-quit',e=>{
    if(quitting)return;
    if (![...terminals.values()].some(t=>t.state==='running')) {quitting=true;return;}
    e.preventDefault();
    if(quitPrompt)return;
    quitPrompt=true;
    dialog.showMessageBox(win,{type:'warning',message:'Quit and stop active terminals?',detail:'Sessions do not survive app quit in this alpha. Detached processes may need separate cleanup.',buttons:['Keep running','Quit and stop'],defaultId:0,cancelId:0}).then(({response})=>{
      quitPrompt=false;
      if(response===1){quitting=true;for(const t of terminals.values()){clearInterval(t.timer);if(t.state==='running')t.proc.kill();}app.quit();}
    });
  });
}
