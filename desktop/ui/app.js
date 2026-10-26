'use strict';
const $=id=>document.getElementById(id);
const api=window.workspace;
const terms=new Map(),pending=new Map();
let state={tasks:[],sessions:[],failures:[],metrics:{}},selectedTask=null,home='',action=null,refreshing=false;
let focusMode=false;
let tabs=[],activeTabId=null,activePaneId=null,tabSeq=0;
let detail=null,detailKey='',detailAt=0;
const opencode={sessions:[],loaded:false,loading:false,pending:[]};
function error(e){const message=e.message||String(e);$('error').textContent=message;$('error').hidden=false;const dialog=document.querySelector('dialog[open]');if(dialog){let line=dialog.querySelector('.error');if(!line){line=node('p',undefined,'error');dialog.prepend(line);}line.textContent=message;}}
function safe(fn){return async (...args)=>{try{$('error').hidden=true;await fn(...args);}catch(e){error(e);}};}
function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;}
function task(){const id=activeTaskId();return state.tasks.find(t=>t.id===id)||null;}
function activeTaskId(){const p=currentPane();return (p&&p.task)||selectedTask;}
function currentTab(){return tabs.find(t=>t.id===activeTabId)||null;}
function currentPane(){return activePaneId?terms.get(activePaneId)||null:null;}
function terminal(){return currentPane();}
async function refresh(){
  if(refreshing)return;refreshing=true;
  try{state=await api.ledger('status');renderTasks();await loadDetail(true);renderInspector();
    if(detail&&detail.ticket_context&&detail.ticket_context.schema==='taskrivet.ticket-context.v1'){
      try{await api.shareContext(detail.ticket_context,$('dashboard-url')?.value||'http://127.0.0.1:7878');$('terminal-hint').textContent=`Dashboard context synced · ${detail.ticket_context.ticket?.key||'standalone'}`;}
      catch(e){$('terminal-hint').textContent='Dashboard context not connected · retrying on refresh.';}
    }
    renderFailures();$('ledger-status').textContent=`LOCAL LEDGER · ${state.tasks.length} TASKS · UPDATED ${new Date().toLocaleTimeString()}`;}
  catch(e){$('ledger-status').textContent='LEDGER UNAVAILABLE';error(e);}
  finally{refreshing=false;}
}
function renderTasks(){
  $('task-list').replaceChildren();
  if(!state.tasks.length)$('task-list').append(node('p','No tasks yet. Use + to define the first outcome.','muted'));
  for(const t of state.tasks){const b=node('button',undefined,'task-item'+(t.id===selectedTask?' active':''));b.append(node('strong',t.id),node('small',t.status));b.onclick=()=>{selectedTask=t.id;renderTasks();renderInspector();};$('task-list').append(b);}
  $('accepted-count').textContent=state.metrics.accepted??0;$('failure-count').textContent=state.failures.reduce((n,f)=>n+f.occurrences,0);
}

/* ---------------------------------------------------------------- session inspector */
// Every useful fact about the focused session and its task, in one column.
function kv(pairs){
  const list=node('dl',undefined,'kv');
  for(const [label,value,note] of pairs){
    if(value===null||value===undefined)continue;
    list.append(node('dt',label));
    const dd=node('dd');
    dd.append(node('span',String(value)));
    if(note)dd.append(node('em',note));
    list.append(dd);
  }
  return list;
}
function showBlock(id,visible){$(id).hidden=!visible;}
function shortSession(id){return id?String(id).slice(0,8):'—';}
function scopeList(t){
  if(!t)return[];
  if(Array.isArray(t.scope))return t.scope;
  try{const parsed=JSON.parse(t.scope);return Array.isArray(parsed)?parsed:[];}catch{return[];}
}
function relativeAge(seconds){
  if(!seconds||seconds<0)return 'unknown';
  if(seconds<60)return `${Math.round(seconds)}s ago`;
  if(seconds<3600)return `${Math.round(seconds/60)}m ago`;
  if(seconds<86400)return `${Math.round(seconds/3600)}h ago`;
  return `${Math.round(seconds/86400)}d ago`;
}
function clock(seconds){
  if(seconds===null||seconds===undefined)return '—';
  const s=Math.max(0,Math.round(seconds));
  return `${Math.floor(s/60)}m ${String(s%60).padStart(2,'0')}s`;
}
async function loadDetail(force=false){
  const p=currentPane(),id=activeTaskId();
  const key=id?`${id}::${p&&p.session?p.session:''}`:'';
  if(!force&&key===detailKey&&Date.now()-detailAt<4000)return;
  if(!id){detail=null;detailKey='';return;}
  try{
    detail=await api.ledger('detail',{task:id,session:p&&p.session?p.session:undefined});
    detailKey=key;detailAt=Date.now();
  }catch(e){detail=null;detailKey='';}
}
function renderInspector(){
  const p=currentPane(),t=task();
  const session=detail&&detail.session?detail.session:null;
  $('session-status').textContent=session?String(session.status).toUpperCase():(p?String(p.state).toUpperCase():'NO SESSION');
  $('session-title').textContent=t?t.id:(p?paneLabel(p):'Keep the objective close.');
  $('session-objective').textContent=t?t.objective:'Open a terminal, or select a task from the queue, to see its brief.';
  const actions=$('checkpoint'),fail=$('fail'),finish=$('finish'),accept=$('accept'),retry=$('retry'),pack=$('pack'),share=$('share-context');
  actions.disabled=!session||session.status!=='active';
  fail.disabled=!session||session.status!=='active';
  finish.disabled=!session||session.status!=='active'||(p&&p.state==='running');
  accept.disabled=!t||t.status!=='review';
  retry.disabled=!t||!['blocked','review'].includes(t.status);
  pack.disabled=!t;
  share.disabled=!(detail&&detail.ticket_context&&detail.ticket_context.schema==='taskrivet.ticket-context.v1');
  const hasSession=!!session;
  showBlock('insp-session-block',hasSession||!!p);
  showBlock('insp-task-block',!!t);
  showBlock('insp-context-block',!!(detail&&detail.context.length));
  showBlock('insp-checkpoints-block',!!(detail&&detail.checkpoints.length));
  showBlock('insp-failures-block',!!(detail&&detail.failures.length));
  showBlock('insp-events-block',!!(detail&&detail.events.length));
  if(p||session){
    const rows=[
      ['Session',session?session.id:null,session?`short ${shortSession(session.id)}`:null],
      ['Status',session?session.status:null],
      ['Owner',session?session.owner:null],
      ['Started',session?relativeAge((Date.now()/1000)-session.created):null],
      ['Lease remaining',session?clock(session.lease_remaining_seconds):null,'expiry blocks ledger progress, not the process'],
      ['Reported tokens',session?session.tokens.toLocaleString():null,'reported, not measured'],
      ['Process',p?(p.state==='running'?'running':(p.exitCode===undefined||p.exitCode===null?'exited':`exited (${p.exitCode})`)):null,p&&p.state==='running'?'survives desktop quit':null],
      ['Folder',p?(p.cwdLive||p.cwd):null,p&&p.cwdLive?'reported by the shell':null],
      ['Command',p?p.shell:null,p&&p.kind==='opencode'?'resumed OpenCode session':null],
      ['PID',p?p.pid||'—':null],
    ];
    $('insp-session').replaceChildren(kv(rows));
  }else $('insp-session').replaceChildren();
  if(t){
    const budget=t.token_budget||0;
    const used=detail?detail.task.reported_tokens:state.sessions.filter(s=>s.task_id===t.id).reduce((n,s)=>n+(s.tokens||0),0);
    $('insp-task').replaceChildren(kv([
      ['Task',t.id],
      ['Status',t.status],
      ['Kind',t.kind],
      ['Objective',t.objective],
      ['Acceptance',t.acceptance],
      ['Scope',scopeList(t).join(', ')||'—'],
      ['Reported usage',`${used.toLocaleString()} / ${budget.toLocaleString()} tokens`,'reported, not measured'],
      ['Remaining',`${Math.max(0,budget-used).toLocaleString()} tokens`],
      ...(detail&&detail.claims.length?[['Resource claims',detail.claims.map(c=>`${c.task} (${c.status}): ${c.shared_keys.join(', ')}`).join(' · '),'other tasks hold these keys']]:[]),
    ]));
  }else $('insp-task').replaceChildren();
  if(detail){
    const pack=detail.pack||{};
    $('insp-context').replaceChildren(kv([
      ['Packet size',pack.bytes===null||pack.bytes===undefined?'unknown':`${pack.bytes.toLocaleString()} bytes`],
      ['Attached items',pack.items],
      ...(pack.omitted&&pack.omitted.length?[['Omitted',pack.omitted.map(o=>`${o.reason} (${String(o.hash||'').slice(0,8)})`).join(', ')]]:[]),
      ...(pack.error?[['Packet error',pack.error]]:[]),
    ]));
    const items=$('insp-context-items');items.replaceChildren();
    for(const c of detail.context){
      const row=node('div',undefined,'insp-row');
      row.append(node('strong',c.source),node('small',`${c.bytes} bytes · priority ${c.priority}${c.expires?` · expires ${new Date(c.expires*1000).toLocaleString()}`:''}${c.expired?' · EXPIRED':''}`));
      items.append(row);
    }
    const checks=$('insp-checkpoints');checks.replaceChildren();
    for(const c of detail.checkpoints){
      const row=node('div',undefined,'insp-row');
      row.append(node('strong',c.summary),node('p',c.evidence),node('small',`next: ${c.next_step} · ${c.tokens.toLocaleString()} tokens · ${relativeAge((Date.now()/1000)-c.created)}`));
      checks.append(row);
    }
    const fails=$('insp-failures');fails.replaceChildren();
    for(const f of detail.failures){
      const row=node('div',undefined,'insp-row');
      row.append(node('strong',f.category),node('p',f.summary),node('small',`${f.occurrences} occurrence${f.occurrences===1?'':'s'} · ${String(f.fingerprint||'').slice(0,12)}`));
      fails.append(row);
    }
    const events=$('insp-events');events.replaceChildren();
    for(const e of detail.events.slice(0,12)){
      const row=node('div',undefined,'insp-row');
      row.append(node('strong',e.type),node('small',`#${e.seq} · ${relativeAge((Date.now()/1000)-e.created)}`));
      events.append(row);
    }
  }
}
function renderFailures(){
  const list=$('failure-list');list.replaceChildren();
  if(!state.failures.length){list.append(node('p','No failures recorded.','muted'));return;}
  for(const f of state.failures){const row=node('div',undefined,'failure-row');row.append(node('small',`${f.occurrences} occurrence${f.occurrences===1?'':'s'}`),node('strong',f.category),node('p',f.summary),node('code',f.fingerprint));list.append(row);}
}
function showView(view){for(const name of ['workspace','failures','tools','dashboard','github']){$(name+'-view').hidden=name!==view;$(name+'-nav').classList.toggle('selected',name===view);} $('view-title').textContent={workspace:'Workspace',failures:'Failure ledger',tools:'Tool catalog',dashboard:'Ticket preview',github:'GitHub activity'}[view];if(view==='workspace')fitActive();}
for(const view of ['workspace','failures','tools','dashboard','github'])$(view+'-nav').onclick=()=>showView(view);

/* ---------------------------------------------------------------- tabs and panes */
function compactTaskLabel(taskId){
  const t=state.tasks.find(item=>item.id===taskId),objective=String(t&&t.objective||'').replace(/\s+/g,' ').trim();
  if(!objective)return taskId||'task';
  return objective.length>30?`${objective.slice(0,29).trimEnd()}…`:objective;
}
function paneLabel(p){if(p.kind==='opencode')return `◆ ${p.title||p.ref||'OpenCode'}`;return p.task?compactTaskLabel(p.task):String(p.shell||'shell').split('/').pop();}
function tabLabel(tab){if(tab.title)return tab.title;const p=terms.get(tab.panes[0]);return p?paneLabel(p):'terminal';}
function tabState(tab){const panes=tab.panes.map(id=>terms.get(id)).filter(Boolean);if(!panes.length)return 'exited';return panes.some(p=>p.state==='running')?'running':'exited';}
function tabContext(tab){
  const panes=tab.panes.map(id=>terms.get(id)).filter(Boolean),p=panes[0],taskId=p&&p.task,t=taskId?state.tasks.find(item=>item.id===taskId):null;
  if(!taskId)return {kind:'standalone',label:'standalone',tone:'neutral',detail:'No ticket context · shell activity is not completion.'};
  const status=t&&t.status?String(t.status):'context unavailable';
  const tone=!t?'stale':(['review','done','accepted'].includes(status)?'review':'bound');
  const session=p&&p.session,shared= session?[...terms.values()].filter(item=>item.session===session).length:0;
  const envelope=p&&p.ticketContext;
  const ownerTab=session&&tabs.find(item=>{const first=terms.get(item.panes[0]);return first&&first.session===session;}),binding=p&&p.binding||(ownerTab&&ownerTab.id===tab.id?'owner':'joined');
  return {kind:'ticket',label:taskId,tone,shared:shared>1,sharedCount:envelope?.session?.shared_count||shared,binding:envelope?.session?.binding||binding,detail:t?`${status} · ${t.objective||'Objective unavailable'}`:'Ticket snapshot unavailable · refresh to re-read source state.',task:t,authority:envelope?.authority};
}
function hideTabContext(){const pop=$('tab-context');pop.hidden=true;pop.replaceChildren();}
function showTabContext(tab,anchor){
  const context=tabContext(tab),pop=$('tab-context');pop.replaceChildren();
  pop.append(node('strong',context.kind==='ticket'?context.label:'Standalone terminal'));
  pop.append(node('span',context.kind==='ticket'?(context.task?`${context.task.status||'unknown'} · ${context.task.kind||'work'}`:'context unavailable'):'No ticket binding','tab-context-state '+context.tone));
  pop.append(node('p',context.detail));
  if(context.kind==='ticket'){
    if(context.shared)pop.append(node('small',`Shared ledger session · ${context.sharedCount} terminal tabs · ${context.binding==='owner'?'owner':'joined'} binding.`));
    pop.append(node('small','Read-only context. This badge does not authorize execution or ticket mutation.'));
  }
  pop.hidden=false;
  const rect=anchor.getBoundingClientRect(),parent=pop.offsetParent?.getBoundingClientRect()||{left:0,top:0};
  pop.style.left=`${Math.max(8,rect.left-parent.left)}px`;pop.style.top=`${rect.bottom-parent.top+6}px`;
}
function renderTabs(){
  const bar=$('tabs');bar.replaceChildren();
  if(!tabs.length){bar.append(node('span','No terminals open','muted'));}
  for(const tab of tabs){
    const b=node('button',undefined,'tab'+(tab.id===activeTabId?' active':''));
    const dot=node('span',tabState(tab)==='running'?'●':'○','tab-dot');
    const context=tabContext(tab),badge=node('span',context.kind==='ticket'?`· ${context.label}${context.shared?` · shared ×${context.sharedCount} · ${context.binding}`:''}`:'· standalone',`tab-context-badge ${context.tone}`);
    badge.title=context.kind==='ticket'?'Show ticket context':'This shell has no ticket context';
    badge.onclick=e=>{e.stopPropagation();showTabContext(tab,badge);};
    b.append(dot,node('span',tabLabel(tab)),badge);
    if(tab.panes.length>1)b.append(node('span',` ${tab.panes.length}`,'tab-count'));
    b.title=`${tabLabel(tab)} · ${context.kind==='ticket'?context.label:'standalone'} · ${tab.panes.length} pane${tab.panes.length===1?'':'s'}`;
    b.onclick=()=>activateTab(tab.id);
    b.oncontextmenu=e=>{e.preventDefault();openMenu(e.clientX,e.clientY,[{label:'Rename tab…',run:()=>renameTab(tab.id)},{label:'Split right',run:()=>splitPane('h')},{label:'Split down',run:()=>splitPane('v')},{label:'Close pane',run:()=>closePane(activePaneId)},{label:'Close tab',run:()=>closeTab(tab.id)},{label:'Close other tabs',run:()=>closeOtherTabs(tab.id)}]);};
    bar.append(b);
  }
  $('terminal-empty').hidden=tabs.length>0;
}
document.addEventListener('mousedown',e=>{if(!e.target.closest('#tab-context')&&!e.target.closest('.tab-context-badge'))hideTabContext();});
function buildTree(nodeRef){
  if(nodeRef.type==='leaf'){
    const p=terms.get(nodeRef.id);
    if(!p)return node('div');
    p.el.classList.toggle('active',p.id===activePaneId);
    return p.el;
  }
  const el=node('div',undefined,'split split-'+nodeRef.dir);
  el.append(buildTree(nodeRef.children[0]),buildTree(nodeRef.children[1]));
  return el;
}
function renderTabTree(tab){
  if(!tab.tree)return;
  tab.container.replaceChildren(buildTree(tab.tree));
  for(const id of tab.panes){
    const p=terms.get(id);
    if(p&&p.state==='running'){try{p.fit.fit();}catch{}}
  }
}
function updatePaneHeads(){
  for(const p of terms.values()){
    if(!p.head)continue;
    p.head.querySelector('.pane-dot').textContent=p.state==='running'?'●':'○';
    p.head.querySelector('.pane-title').textContent=paneLabel(p);
    p.head.querySelector('.pane-path').textContent=p.cwdLive||p.cwd||'';
    p.el.classList.toggle('exited',p.state!=='running');
  }
}
function applyPaneFocus(){
  for(const p of terms.values())if(p.el)p.el.classList.toggle('active',p.id===activePaneId);
}
function activateTab(id){
  activeTabId=id;
  const tab=currentTab();
  if(tab&&!tab.panes.includes(activePaneId))activePaneId=tab.panes[0]||null;
  for(const other of tabs)other.container.classList.toggle('active',other.id===activeTabId);
  applyPaneFocus();
  renderTabs();renderTerminalStatus();renderInspector();
  fitActive();
}
function activatePane(id){
  const p=terms.get(id);
  if(!p)return;
  activePaneId=id;
  const tab=tabs.find(t=>t.panes.includes(id));
  if(tab&&tab.id!==activeTabId){activateTab(tab.id);return;}
  applyPaneFocus();
  if(p.task)selectedTask=p.task;
  renderTabs();renderTerminalStatus();renderTasks();
  loadDetail(true).then(renderInspector);
  requestAnimationFrame(()=>{try{p.fit.fit();}catch(e){error(new Error('Terminal could not be resized to the available space.'));}p.xterm.focus();});
}
function stateLabel(t){if(!t)return 'NO SHELL RUNNING';if(t.state==='running')return 'PROCESS ACTIVE · SURVIVES APP QUIT';if(t.state==='disconnected')return 'CONNECTION LOST';return `EXITED · ${t.exitCode??'—'}`;}
function renderTerminalStatus(){
  const t=terminal();
  $('terminal-path').textContent=t?(t.cwdLive||t.cwd):'Choose a folder to begin';
  $('terminal-state').textContent=stateLabel(t);
  $('terminal-hint').textContent=focusMode
    ?(t?`${t.cwd} · ${stateLabel(t)}`:'No terminal open')
    :(t?(t.session?'Linked to a ledger session. Shell activity is not verified progress.':'Unassigned session · survives app quit · no completion inferred.'):'Shells run with your Mac user permissions.');
  $('stop-terminal').disabled=!t||t.state!=='running';
  $('remove-terminal').disabled=!t||t.state==='running';
}
function receive(p){const t=terms.get(p.id);if(!t){const q=pending.get(p.id)||[];q.push(p);if(q.length>32)q.shift();pending.set(p.id,q);return;}if(p.seq<=t.seq)return;t.seq=p.seq;t.xterm.write(p.data);}
function paneElement(p){
  const el=node('div',undefined,'terminal-pane');
  el.dataset.term=p.id;
  const head=node('div',undefined,'pane-head');
  head.append(node('span',undefined,'pane-dot'),node('span',undefined,'pane-title'),node('span',undefined,'pane-path'));
  const close=node('button','×','pane-close');
  close.title='Close this pane';
  close.onclick=e=>{e.stopPropagation();closePane(p.id);};
  head.append(close);
  const screen=node('div',undefined,'pane-screen');
  el.append(head,screen);
  p.el=el;p.screen=screen;p.head=head;
  el.addEventListener('mousedown',()=>activatePane(p.id));
  el.addEventListener('contextmenu',e=>{e.preventDefault();openMenu(e.clientX,e.clientY,[{label:'Split right',run:()=>splitPane('h')},{label:'Split down',run:()=>splitPane('v')},{label:'Copy selection',run:copySelection},{label:'Clear scrollback',run:()=>p.xterm.clear()},{label:'Close pane',run:()=>closePane(p.id)}]);});
  return el;
}
function addTerminal(info,opts={}){
  const p={...info,xterm:null,fit:null,el:null,seq:0,cwdLive:null,tool:opts.tool||null};
  const el=paneElement(p);
  const xterm=new Terminal({cursorBlink:true,fontSize:12,fontFamily:'"SFMono-Regular", Menlo, monospace',scrollback:3000,allowProposedApi:false,theme:{background:'#10191e',foreground:'#d1e1dc',cursor:'#79d3b4',selectionBackground:'#305d52'}});
  const fit=new FitAddon.FitAddon();xterm.loadAddon(fit);xterm.open(el.querySelector('.pane-screen'));
  // Never accept terminal-initiated clipboard writes or external links.
  xterm.parser.registerOscHandler(52,()=>true);
  // The shell reports its own folder when it supports OSC 7; we only observe it.
  xterm.parser.registerOscHandler(7,data=>{const path=String(data||'').replace(/^file:\/\/[^/]*\//,'/');if(path.startsWith('/'))p.cwdLive=path;updatePaneHeads();return true;});
  xterm.onData(data=>api.write(info.id,data).catch(error));
  xterm.onResize(({cols,rows})=>api.resize(info.id,cols,rows).catch(error));
  xterm.onTitleChange(title=>{p.osTitle=title;updatePaneHeads();});
  xterm.attachCustomKeyEventHandler(ev=>{
    const combo=commandCombo(ev);
    if(!combo)return true;
    // Cmd-C stays with the shell when nothing is selected.
    if(combo==='copy'&&!p.xterm.hasSelection())return true;
    handleCommand(combo);
    return false;
  });
  p.xterm=xterm;p.fit=fit;
  terms.set(info.id,p);
  for(const chunk of info.chunks||[])receive({id:info.id,...chunk});
  for(const chunk of pending.get(info.id)||[])receive(chunk);pending.delete(info.id);
  new ResizeObserver(()=>{if(p.id===activePaneId&&el.offsetWidth>0)fit.fit();}).observe(el);
  if(opts.tab){
    const tab=opts.tab;
    tab.panes.push(info.id);
    if(opts.splitOf)insertSplit(tab,opts.splitOf,info.id,opts.dir||'h');
    else tab.tree={type:'leaf',id:info.id};
    renderTabTree(tab);
  }else{
    const tab={id:`tab-${++tabSeq}`,title:null,panes:[info.id],tree:{type:'leaf',id:info.id},container:node('div',undefined,'tab-panes')};
    tabs.push(tab);
    $('tab-panes').append(tab.container);
    renderTabTree(tab);
  }
  updatePaneHeads();renderTabs();
  activatePane(info.id);
  return p;
}
function insertSplit(tab,sourceId,newId,dir){
  const replace=(ref)=>{
    if(!ref)return null;
    if(ref.type==='leaf')return ref.id===sourceId?{type:'split',dir,children:[{type:'leaf',id:sourceId},{type:'leaf',id:newId}]}:ref;
    const children=ref.children.map(replace);
    return children[0]?{...ref,children}:ref;
  };
  tab.tree=replace(tab.tree);
}
function removeLeaf(ref,id){
  if(!ref)return null;
  if(ref.type==='leaf')return ref.id===id?null:ref;
  const children=ref.children.map(c=>removeLeaf(c,id)).filter(Boolean);
  if(!children.length)return null;
  if(children.length===1)return children[0];
  return {...ref,children};
}
async function splitPane(dir){
  const source=currentPane();
  if(!source)return;
  const tab=currentTab();
  if(!tab)return;
  const info=await api.createTerminal({cwd:source.cwd,task:source.task||null,session:source.session||null});
  addTerminal(info,{tab,splitOf:source.id,dir});
  renderTabs();
}
async function closePane(id){
  const p=terms.get(id);
  if(!p)return;
  if(p.state==='running'){
    const stopped=await api.stop(id);
    if(stopped===false)return;
  }
  await api.remove(id);
  p.xterm.dispose();p.el.remove();terms.delete(id);
  const tab=tabs.find(t=>t.panes.includes(id));
  if(tab){
    tab.panes=tab.panes.filter(x=>x!==id);
    tab.tree=removeLeaf(tab.tree,id);
    if(!tab.panes.length){closeTab(tab.id,false);return;}
    if(activePaneId===id)activePaneId=tab.panes[0];
    renderTabTree(tab);
  }
  if(activePaneId===id)activePaneId=tabs.length?tabs[tabs.length-1].panes[0]:null;
  renderTabs();renderTerminalStatus();renderInspector();
  fitActive();
}
async function closeTab(id,withPanes=true){
  const tab=tabs.find(t=>t.id===id);
  if(!tab)return;
  if(withPanes)for(const pid of [...tab.panes])await closePane(pid);
  tab.container.remove();
  tabs=tabs.filter(t=>t.id!==id);
  if(activeTabId===id){activeTabId=tabs.length?tabs[tabs.length-1].id:null;activePaneId=activeTabId?tabs.find(t=>t.id===activeTabId).panes[0]:null;}
  renderTabs();renderTerminalStatus();renderInspector();
}
async function closeOtherTabs(id){
  for(const tab of [...tabs])if(tab.id!==id)await closeTab(tab.id);
}
function renameTab(id){
  const tab=tabs.find(t=>t.id===id);
  if(!tab)return;
  const name=window.prompt('Tab name',tabLabel(tab));
  if(name===null)return;
  tab.title=name.trim().slice(0,60);
  renderTabs();
}
async function copySelection(){
  const p=currentPane();
  if(!p)return;
  const text=p.xterm.getSelection();
  if(!text)return;
  try{await navigator.clipboard.writeText(text);$('terminal-hint').textContent='Selection copied to the clipboard.';}catch{error(new Error('The clipboard is not available from this window.'));}
}

/* ---------------------------------------------------------------- find in scrollback */
const find={query:'',matches:[],index:-1};
function searchBuffer(term,needle){
  const buffer=term.xterm.buffer.active;
  const matches=[];
  let segments=[],logical='';
  const flush=()=>{
    if(!segments.length)return;
    const haystack=logical.toLowerCase();
    let at=haystack.indexOf(needle);
    while(at>=0){
      for(const s of segments){
        if(at>=s.offset&&at<s.offset+s.text.length){matches.push({y:s.y,col:at-s.offset});break;}
      }
      at=haystack.indexOf(needle,at+needle.length);
    }
    segments=[];logical='';
  };
  for(let y=0;y<buffer.length;y++){
    const line=buffer.getLine(y);
    if(!line)continue;
    const text=line.translateToString(true);
    if(line.isWrapped&&segments.length){segments[segments.length-1].text+=text;logical+=text;continue;}
    flush();
    segments=[{y,text,offset:0}];logical=text;
  }
  flush();
  return matches;
}
function runFind(){
  const p=currentPane();
  const count=$('find-count');
  if(!p){count.textContent='no pane';return;}
  if(!find.query){count.textContent='no matches';return;}
  const matches=searchBuffer(p,find.query.toLowerCase());
  find.matches=matches;find.index=matches.length?0:-1;
  count.textContent=matches.length?`${matches.length} match${matches.length===1?'':'es'}`:'no matches';
  if(matches.length)jumpToMatch();
}
function jumpToMatch(step=0){
  if(!find.matches.length)return;
  find.index=(find.index+step+find.matches.length)%find.matches.length;
  const m=find.matches[find.index];
  const p=currentPane();
  if(!p)return;
  p.xterm.scrollToLine(m.y);
  p.xterm.select(m.col,m.y,find.query.length);
  $('find-count').textContent=`${find.index+1} of ${find.matches.length}`;
}
function openFind(){
  $('find-bar').hidden=false;
  $('find-input').focus();
  $('find-input').select();
  if(find.query)runFind();
}
function closeFind(){
  $('find-bar').hidden=true;
  const p=currentPane();
  if(p){p.xterm.clearSelection();p.xterm.focus();}
}

/* ---------------------------------------------------------------- command palette */
const commands=[
  {label:'New terminal tab',combo:'⌘T',run:()=>openTerminal()},
  {label:'Split pane right',combo:'⌘D',run:()=>splitPane('h')},
  {label:'Split pane down',combo:'⇧⌘D',run:()=>splitPane('v')},
  {label:'Find in scrollback',combo:'⌘F',run:openFind},
  {label:'Terminal focus mode',combo:'⇧⌘F',run:()=>setFocus(!focusMode)},
  {label:'Create a task',run:()=>$('task-dialog').showModal()},
  {label:'Record checkpoint',run:()=>$('checkpoint').click()},
  {label:'Record failure',run:()=>$('fail').click()},
  {label:'Submit for review',run:()=>$('finish').click()},
  {label:'Accept result',run:()=>$('accept').click()},
  {label:'Retry after reconciliation',run:()=>$('retry').click()},
  {label:'Inspect context packet',run:()=>$('pack').click()},
  {label:'Refresh the local ledger',run:()=>refresh()},
  {label:'Show the failure ledger',run:()=>showView('failures')},
  {label:'Show the tool catalog',run:()=>showView('tools')},
  {label:'Show the ticket preview',run:()=>showView('dashboard')},
  {label:'Show GitHub activity',run:()=>showView('github')},
  {label:'Copy the session id',run:async()=>{const p=currentPane();if(p&&p.session){try{await navigator.clipboard.writeText(p.session);$('terminal-hint').textContent='Session id copied.';}catch{error(new Error('The clipboard is not available from this window.'));}}}},
  {label:'Close the focused pane',run:()=>closePane(activePaneId)},
  {label:'Close the focused tab',run:()=>closeTab(activeTabId)},
];
let paletteIndex=0;
function openPalette(){
  $('palette-input').value='';
  $('palette-dialog').showModal();
  renderPalette();
  $('palette-input').focus();
}
function renderPalette(){
  const query=($('palette-input').value||'').toLowerCase();
  const rows=commands.filter(c=>!query||c.label.toLowerCase().includes(query));
  paletteIndex=Math.min(paletteIndex,Math.max(0,rows.length-1));
  const list=$('palette-list');list.replaceChildren();
  rows.forEach((c,i)=>{
    const li=node('li',undefined,i===paletteIndex?'selected':'');
    li.append(node('span',c.label));
    if(c.combo)li.append(node('em',c.combo));
    li.onclick=()=>{ $('palette-dialog').close(); c.run(); };
    list.append(li);
  });
  if(!rows.length)list.append(node('li','No matching command','empty'));
}
$('palette-input').addEventListener('input',()=>{paletteIndex=0;renderPalette();});
$('palette-input').addEventListener('keydown',e=>{
  const rows=[...$('palette-list').children].filter(li=>!li.classList.contains('empty'));
  if(e.key==='Enter'){e.preventDefault();const c=commands.filter(c=>!$('palette-input').value||c.label.toLowerCase().includes($('palette-input').value.toLowerCase()))[paletteIndex];if(c){$('palette-dialog').close();c.run();}}
  if(e.key==='ArrowDown'){e.preventDefault();paletteIndex=Math.min(paletteIndex+1,rows.length-1);renderPalette();}
  if(e.key==='ArrowUp'){e.preventDefault();paletteIndex=Math.max(paletteIndex-1,0);renderPalette();}
});
$('palette-toggle').onclick=openPalette;

/* ---------------------------------------------------------------- context menu */
function openMenu(x,y,items){
  const menu=$('ctx-menu');
  menu.replaceChildren();
  for(const item of items){
    const b=node('button',item.label);
    b.onclick=()=>{menu.hidden=true;item.run();};
    menu.append(b);
  }
  menu.hidden=false;
  const rect=menu.getBoundingClientRect();
  menu.style.left=`${Math.min(x,window.innerWidth-rect.width-12)}px`;
  menu.style.top=`${Math.min(y,window.innerHeight-rect.height-12)}px`;
}
document.addEventListener('click',e=>{if(!e.target.closest('#ctx-menu'))$('ctx-menu').hidden=true;});

/* ---------------------------------------------------------------- shortcuts */
function commandCombo(ev){
  if(!ev.metaKey||ev.ctrlKey||ev.altKey)return null;
  const key=ev.key.toLowerCase();
  if(ev.shiftKey&&key==='d')return 'split-down';
  if(ev.shiftKey&&key==='f')return 'focus';
  if(ev.shiftKey)return null;
  if(key==='t')return 'new-tab';
  if(key==='d')return 'split-right';
  if(key==='f')return 'find';
  if(key==='k')return 'palette';
  if(key==='w')return 'close';
  if(key==='c')return 'copy';
  if(/^[1-9]$/.test(key))return 'tab-'+key;
  return null;
}
function handleCommand(combo){
  if(combo==='new-tab'){openTerminal();return;}
  if(combo==='split-right'){splitPane('h');return;}
  if(combo==='split-down'){splitPane('v');return;}
  if(combo==='find'){openFind();return;}
  if(combo==='palette'){openPalette();return;}
  if(combo==='focus'){setFocus(!focusMode);return;}
  if(combo==='copy'){copySelection();return;}
  if(combo==='close'){closePane(activePaneId);return;}
  if(combo.startsWith('tab-')){
    const index=Number(combo.slice(4))-1;
    if(tabs[index])activateTab(tabs[index].id);
  }
}
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){
    if(!$('find-bar').hidden){closeFind();return;}
    if(!$('ctx-menu').hidden){$('ctx-menu').hidden=true;return;}
  }
  if(e.metaKey&&e.shiftKey&&e.key.toLowerCase()==='t'){e.preventDefault();openTerminal();}
  if(e.metaKey&&e.key.toLowerCase()==='k'&&!e.shiftKey&&!document.querySelector('dialog[open]')){e.preventDefault();openPalette();}
});
$('split-right').onclick=()=>splitPane('h');
$('split-down').onclick=()=>splitPane('v');
$('find-toggle').onclick=openFind;
$('find-close').onclick=closeFind;
$('find-prev').onclick=()=>jumpToMatch(-1);
$('find-next').onclick=()=>jumpToMatch(1);
$('find-input').addEventListener('input',e=>{find.query=e.target.value;runFind();});
$('find-input').addEventListener('keydown',e=>{
  if(e.key==='Enter'){e.preventDefault();jumpToMatch(e.shiftKey?-1:1);}
});

/* ---------------------------------------------------------------- terminal lifecycle */
api.onData(receive);
api.onDisconnect(()=>{for(const t of terms.values())t.state='disconnected';renderTabs();updatePaneHeads();renderInspector();renderTerminalStatus();error(new Error('Session connection lost. Reopen the app to reconcile. Commands have not been replayed.'));});
api.onExit(({id,exitCode})=>{const t=terms.get(id);if(!t)return;t.state='exited';t.exitCode=exitCode;t.xterm.writeln(`\r\n[Process exited with code ${exitCode}. Task acceptance is unchanged.]`);updatePaneHeads();renderTabs();if(activePaneId===id)renderInspector();refresh();});
$('add-task').onclick=()=>$('task-dialog').showModal();
$('task-form').onsubmit=safe(async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));await api.ledger('create',data);selectedTask=data.id;$('task-dialog').close();e.target.reset();await refresh();});
let launchTool=null, toolRows=[];
function openTerminal(tool=null){
  launchTool=typeof tool==='string'?tool:null;
  $('launch-tool').textContent=launchTool?`Launch ${launchTool} directly, with no added arguments. Existing account settings apply.`:'Open your login shell.';
  $('cwd').value=home;const select=$('terminal-task');select.replaceChildren(new Option('Unassigned shell',''));
  for(const t of state.tasks.filter(t=>t.status==='ready'))select.add(new Option(t.id,t.id));
  const active=state.tasks.find(t=>t.id===selectedTask&&t.status==='running');
  if(active)select.add(new Option(`${active.id} · active session`,active.id));
  if(task()?.status==='ready'||active)select.value=selectedTask;
  $('inherit-ticket-context').checked=false;
  $('inherit-ticket-context').disabled=!active;
  updateTicketContextNote(active);
  $('terminal-dialog').showModal();
}
function updateTicketContextNote(active=state.tasks.find(t=>t.id===$('terminal-task').value&&t.status==='running')){
  const checked=$('inherit-ticket-context').checked;
  $('ticket-context-note').textContent=active
    ?(checked?`Authorized: this CLI will join ${active.id}'s active session. Ticket mutation and acceptance remain separate.`:`Unchecked: standalone CLI. Checked: explicitly join ${active.id}'s active session; this does not authorize ticket mutation or acceptance.`)
    :'Select an active task to enable explicit ticket-context inheritance. Standalone CLI launch remains the default.';
}
$('inherit-ticket-context').onchange=()=>updateTicketContextNote();
$('new-terminal').onclick=openTerminal;$('empty-new').onclick=openTerminal;$('tabs-new').onclick=openTerminal;
$('choose-folder').onclick=safe(async()=>{const folder=await api.chooseDirectory();if(folder)$('cwd').value=folder;});
$('terminal-form').onsubmit=safe(async e=>{e.preventDefault();const button=e.target.querySelector('button.primary');button.disabled=true;try{
  const taskId=$('terminal-task').value||null,inherit=$('inherit-ticket-context').checked;
  let session=null;
  if(inherit){
    const active=state.tasks.find(t=>t.id===taskId&&t.status==='running'),record=state.sessions.find(s=>s.task_id===taskId&&s.status==='active');
    if(!active||!record)throw new Error('Active ticket context is unavailable; refresh the ledger before opening this CLI.');
    session=record.id;
  }
  const info=await api.createTerminal({cwd:$('cwd').value,task:taskId,session,tool:launchTool});
  $('terminal-dialog').close();showView('workspace');addTerminal(info);await refresh();
}finally{button.disabled=false;}});
$('share-context').onclick=safe(async()=>{if(!detail||!detail.ticket_context)throw new Error('No ticket context is available to share.');if(!confirm('Share this read-only Taskrivet context with the local AI Dashboard?\n\nNo ticket mutation or execution authorization is included.'))return;const result=await api.shareContext(detail.ticket_context,$('dashboard-url')?.value||'http://127.0.0.1:7878');$('terminal-hint').textContent=`Dashboard received ${result.ticket?.key||'standalone'} context.`;});
$('stop-terminal').onclick=safe(async()=>{if(terminal())await api.stop(activePaneId);});
$('remove-terminal').onclick=()=>closePane(activePaneId);
// Terminal focus: collapse the navigation so the terminal owns the window.
function fitActive(){requestAnimationFrame(()=>{const t=terminal();if(!t||!t.el||t.el.offsetWidth<1)return;try{t.fit.fit();}catch(e){error(new Error('Terminal could not be resized to the available space.'));}});}
function setFocus(on){
  focusMode=on;document.body.classList.toggle('focus-mode',on);
  $('focus-toggle').textContent=on?'⤡':'⤢';
  $('focus-toggle').setAttribute('aria-pressed',String(on));
  $('focus-toggle').title=on?'Leave terminal focus (Command-Shift-F)':'Terminal focus: hide navigation (Command-Shift-F)';
  try{localStorage.setItem('taskrivet.focus-mode',on?'1':'0');}catch{}
  renderTerminalStatus();
  fitActive();
}
$('focus-toggle').onclick=()=>setFocus(!focusMode);
try{if(localStorage.getItem('taskrivet.focus-mode')==='1')setFocus(true);}catch{}
// OpenCode sessions: local metadata only, one resumable session per tab.
const OPENCODE_BATCH=12;
function openCodeTabs(){return new Set([...terms.values()].map(t=>t.ref).filter(Boolean));}
function relativeTime(ms){if(!ms)return 'no timestamp';const minutes=Math.round((Date.now()-ms)/60000);if(minutes<1)return 'just now';if(minutes<60)return `${minutes}m ago`;const hours=Math.round(minutes/60);if(hours<24)return `${hours}h ago`;return `${Math.round(hours/24)}d ago`;}
function filteredOpenCode(){const query=($('opencode-search').value||'').toLowerCase();return opencode.sessions.filter(s=>!query||(s.title+' '+s.id+' '+s.directory).toLowerCase().includes(query));}
function renderOpenCode(){
  const list=$('opencode-list');list.replaceChildren();
  const open=openCodeTabs(),rows=filteredOpenCode();
  if(!rows.length){list.append(node('p',opencode.loaded?'No OpenCode session matches this filter.':'OpenCode session metadata has not been read yet.','muted'));return;}
  for(const s of rows){
    const row=node('div',undefined,'opencode-row'),info=node('div');
    info.append(node('strong',s.title||'Untitled session'),node('small',`${s.directory||'unknown folder'} · ${relativeTime(s.updated)} · ${s.id}`));
    const actions=node('div',undefined,'row-actions');
    if(open.has(s.id))actions.append(node('span','OPEN IN A TAB','badge'));
    else if(s.directory_available===false){actions.append(node('span','FOLDER MISSING','badge missing'));}
    else{const b=node('button','Open tab');b.onclick=safe(()=>openOpenCodeSession(s));actions.append(b);}
    row.append(info,actions);list.append(row);
  }
}
async function loadOpenCode(force=false){
  if(opencode.loading)return;
  if(opencode.loaded&&!force){renderOpenCode();return;}
  opencode.loading=true;$('opencode-status').textContent='Reading local OpenCode session metadata…';
  try{
    const result=await api.opencodeSessions({limit:120});
    opencode.sessions=Array.isArray(result.sessions)?result.sessions:[];
    opencode.loaded=true;
    $('opencode-count').textContent=String(opencode.sessions.length);
    $('opencode-status').textContent=result.available
      ?`${result.session_count} local OpenCode sessions · metadata only, no transcripts · read ${new Date(result.observed_at*1000).toLocaleTimeString()}`
      :`OpenCode sessions unavailable: ${result.reason||'unknown reason'}`;
    renderOpenCode();
  }catch(e){$('opencode-status').textContent='OpenCode session metadata unavailable. No session was opened.';error(e);}
  finally{opencode.loading=false;}
}
async function openOpenCodeSession(s){
  showView('workspace');
  const info=await api.createTerminal({opencode:{id:s.id,directory:s.directory,title:s.title}});
  addTerminal(info);renderOpenCode();
}
$('opencode-toggle').onclick=()=>{const drawer=$('opencode-drawer'),open=drawer.hidden;drawer.hidden=!open;$('opencode-toggle').setAttribute('aria-expanded',String(open));if(open)loadOpenCode();};
$('opencode-refresh').onclick=safe(()=>loadOpenCode(true));
$('opencode-search').oninput=renderOpenCode;
$('opencode-open-all').onclick=()=>{
  const open=openCodeTabs(),rows=filteredOpenCode().filter(s=>!open.has(s.id)&&s.directory_available!==false);
  if(!rows.length){$('opencode-status').textContent='Every matching OpenCode session is already open in a tab.';return;}
  const batch=rows.slice(0,OPENCODE_BATCH);
  opencode.pending=batch;
  $('opencode-dialog-title').textContent='Open each session as its own tab';
  $('opencode-dialog-detail').textContent=`${batch.length} of ${rows.length} matching session${rows.length===1?'':'s'} will start as separate OpenCode terminals in their own working folders. Each tab is a live agent process. Sessions are resumed, not copied or rewritten.`;
  $('opencode-dialog').showModal();
};
$('opencode-form').onsubmit=safe(async e=>{e.preventDefault();const batch=opencode.pending;$('opencode-dialog').close();let opened=0,failed=0;
  for(const s of batch){try{await openOpenCodeSession(s);opened++;}catch(err){failed++;error(err);}}
  $('opencode-status').textContent=`${opened} session${opened===1?'':'s'} opened in their own tab${failed?` · ${failed} failed`:''} · ${new Date().toLocaleTimeString()}`;
  renderOpenCode();});
const definitions={checkpoint:['Record checkpoint',['summary','evidence','next','tokens']],fail:['Record failure',['category','summary']],finish:['Submit for review',['evidence']],accept:['Accept result',['reason']],retry:['Retry after reconciliation',['reason']]};
for(const name of Object.keys(definitions))$(name).onclick=()=>{
  const pane=currentPane();
  action={name,task:activeTaskId(),session:pane&&pane.session};
  const [title,fields]=definitions[name];$('action-title').textContent=title;$('action-fields').replaceChildren();
  for(const field of fields){const label=node('label',{summary:'What changed',evidence:'Evidence or artifact reference',next:'Next step',tokens:'Cumulative session tokens (reported)',category:'Failure category',reason:'Reason and reconciliation evidence'}[field]);const input=node(['summary','evidence','next','reason'].includes(field)?'textarea':'input');input.name=field;input.required=true;if(field==='tokens'){input.type='number';input.min='0';input.value=state.sessions.find(s=>s.id===action.session)?.tokens??0;}label.append(input);$('action-fields').append(label);}
  $('action-dialog').showModal();
};
$('action-form').onsubmit=safe(async e=>{e.preventDefault();const data={...Object.fromEntries(new FormData(e.target)),task:action.task,session:action.session};if('tokens'in data)data.tokens=Number(data.tokens);await api.ledger(action.name,data);$('action-dialog').close();await refresh();});
$('pack').onclick=safe(async()=>{const result=await api.ledger('pack',{task:activeTaskId()});$('packet').textContent=JSON.stringify(result,null,2);$('packet-dialog').showModal();});
for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>b.closest('dialog').close();
(async()=>{try{const initial=await api.bootstrap();home=initial.home;$('app-version').textContent=`VERSION ${initial.version||'UNKNOWN'}`;$('github-repo').value=initial.githubRepo||'';for(const t of initial.terminals)addTerminal(t);await refresh();}catch(e){$('app-version').textContent='VERSION UNKNOWN';error(e);}})();
setInterval(()=>{if(!document.hidden)refresh();},15000);

function renderTools(){
  const query=$('tool-search').value.toLowerCase(),filter=$('tool-filter').value;
  const rows=toolRows.filter(t=>(t.name+' '+t.id).toLowerCase().includes(query)&&(filter==='all'||filter===t.category||filter==='installed'&&t.installed||filter==='history'&&(t.recent_count+t.undated_count)>0));
  $('tool-list').replaceChildren();
  for(const t of rows){const row=node('div',undefined,'tool-row'),info=node('div');info.append(node('strong',t.name),node('small',`${t.id} · ${t.category} · ${t.installed?'executable detected':'not detected'} · recent ${t.recent_count} / undated ${t.undated_count}`));const launch=node('button','Launch…');launch.disabled=!t.installed;launch.onclick=()=>openTerminal(t.id);row.append(info,launch);$('tool-list').append(row);}
}
async function loadTools(history=false){const result=await api.ledger('tools',{history});toolRows=result.tools;$('tool-count').textContent=`${result.installed} installed commands · ${result.agent_profiles} coding-agent discovery profiles · account readiness unknown · checked ${new Date().toLocaleTimeString()}`;renderTools();}
$('tools-refresh').onclick=safe(()=>loadTools());$('tools-history').onclick=safe(()=>loadTools(true));
$('tool-search').oninput=renderTools;$('tool-filter').onchange=renderTools;
$('tools-nav').onclick=safe(async()=>{showView('tools');if(!toolRows.length)await loadTools();});

let dashboardPage=null,dashboardOffset=0;
function renderDashboard(){
  const list=$('dashboard-list');list.replaceChildren();if(!dashboardPage)return;
  const query=$('dashboard-search').value.toLowerCase(),project=$('dashboard-project').value;
  const rows=dashboardPage.tickets.filter(t=>(!project||t.project===project)&&(t.key+' '+t.title).toLowerCase().includes(query));
  if(!rows.length)list.append(node('p','No work tickets match this page and filter. This is not a complete-board result.','muted'));
  for(const t of rows){const row=node('div',undefined,'failure-row');row.append(node('strong',`${t.key} · ${t.title}`),node('small',`${t.project} · ${t.stage} · priority ${t.priority??'unknown'} · ${t.readiness}`));const detail=node('details');detail.append(node('summary','Execution prerequisites'));const ul=node('ul');for(const reason of t.reasons)ul.append(node('li',reason));detail.append(ul);row.append(detail);list.append(row);}
}
async function loadDashboard(offset=0){
  $('dashboard-refresh').disabled=true;$('dashboard-next').disabled=true;$('dashboard-prev').disabled=true;
  try{const page=await api.ledger('dashboard',{url:$('dashboard-url').value,status:$('dashboard-status').value,offset});dashboardPage=page;dashboardOffset=offset;
  $('dashboard-summary').textContent=`${page.returned} work tickets returned · source total ${page.source_total??'unknown'} · offset ${offset} · source generated ${page.source_generated_at??'unknown'} · ${page.stale?'STALE / UNKNOWN':'source reports fresh'} · fetched ${new Date().toLocaleTimeString()}. ${page.coverage} · handoff taskrivet.handoff-receipt.v1 · history taskrivet.handoff-history.v1`;
  $('dashboard-project').replaceChildren(new Option('All returned projects',''));for(const p of page.projects)$('dashboard-project').add(new Option(p,p));
  $('dashboard-prev').disabled=offset===0;$('dashboard-next').disabled=page.has_more!==true;renderDashboard();
  }catch(e){dashboardPage=null;$('dashboard-list').replaceChildren();$('dashboard-summary').textContent='Source unavailable or incomplete. No tickets admitted; refresh to retry.';throw e;}finally{$('dashboard-refresh').disabled=false;}
}
$('dashboard-refresh').onclick=safe(()=>loadDashboard());$('dashboard-next').onclick=safe(()=>loadDashboard(dashboardOffset+100));$('dashboard-prev').onclick=safe(()=>loadDashboard(Math.max(0,dashboardOffset-100)));
$('dashboard-search').oninput=renderDashboard;$('dashboard-project').onchange=renderDashboard;
$('dashboard-status').onchange=()=>{dashboardPage=null;dashboardOffset=0;$('dashboard-list').replaceChildren();$('dashboard-prev').disabled=true;$('dashboard-next').disabled=true;$('dashboard-summary').textContent='Source filter changed. Read a new page to refresh.';};

setInterval(()=>{if(dashboardPage&&Date.now()/1000-dashboardPage.observed_at>300){$('dashboard-summary').textContent='STALE: this preview is over five minutes old. Read a new source page before making a decision.';}},15000);

api.onIntegrationError(p=>error(new Error(p.message)));
$('github-refresh').onclick=safe(async()=>{const r=await api.ledger('github-status',{repo:$('github-repo').value});$('github-summary').textContent=r.last_poll?`Last observed ${new Date(r.last_poll*1000).toLocaleString()} · historical completeness not guaranteed · dispatch disabled`:'No completed poll recorded.';$('github-coverage').textContent=JSON.stringify({coverage:r.coverage,responses:r.responses},null,2);$('github-list').replaceChildren();for(const e of r.recent){const row=node('div',undefined,'failure-row');row.append(node('strong',e.summary),node('p',e.kind+' · '+e.action),node('small',e.url));$('github-list').append(row);}});
