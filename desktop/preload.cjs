const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('workspace', {
  bootstrap:()=>ipcRenderer.invoke('bootstrap'),
  ledger:(action,data)=>ipcRenderer.invoke('ledger',action,data),
  chooseDirectory:()=>ipcRenderer.invoke('choose-directory'),
  createTerminal:options=>ipcRenderer.invoke('terminal:create',options),
  write:(id,data)=>ipcRenderer.invoke('terminal:write',id,data),
  resize:(id,cols,rows)=>ipcRenderer.invoke('terminal:resize',id,cols,rows),
  stop:id=>ipcRenderer.invoke('terminal:stop',id),
  remove:id=>ipcRenderer.invoke('terminal:remove',id),
  onIntegrationError:callback=>{ipcRenderer.on('integration:error',(_e,p)=>callback(p));},
  onDisconnect:callback=>{ipcRenderer.on('terminal:disconnected',callback);},
  onData:callback=>{const listener=(_e,p)=>callback(p);ipcRenderer.on('terminal:data',listener);return()=>ipcRenderer.removeListener('terminal:data',listener);},
  onExit:callback=>{const listener=(_e,p)=>callback(p);ipcRenderer.on('terminal:exit',listener);return()=>ipcRenderer.removeListener('terminal:exit',listener);}
});
