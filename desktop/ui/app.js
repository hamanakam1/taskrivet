'use strict';
const $=id=>document.getElementById(id);
const api=window.workspace;
const terms=new Map(),pending=new Map();
let state={tasks:[],sessions:[],failures:[],metrics:{}},selectedTask=null,activeTerminal=null,home='',action=null,refreshing=false;
function error(e){const message=e.message||String(e);$('error').textContent=message;$('error').hidden=false;const dialog=document.querySelector('dialog[open]');if(dialog){let line=dialog.querySelector('.error');if(!line){line=node('p',undefined,'error');dialog.prepend(line);}line.textContent=message;}}
function safe(fn){return async (...args)=>{try{$('error').hidden=true;await fn(...args);}catch(e){error(e);}};}
function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;}
function task(){return state.tasks.find(t=>t.id===selectedTask);}
function terminal(){return terms.get(activeTerminal);}
async function refresh(){
  if(refreshing)return;refreshing=true;
  try{state=await api.ledger('status');renderTasks();renderInspector();renderFailures();$('ledger-status').textContent=`LOCAL LEDGER · ${state.tasks.length} TASKS · UPDATED ${new Date().toLocaleTimeString()}`;}
  catch(e){$('ledger-status').textContent='LEDGER UNAVAILABLE';error(e);}
  finally{refreshing=false;}
}
function renderTasks(){
  $('task-list').replaceChildren();
  if(!state.tasks.length)$('task-list').append(node('p','No tasks yet. Use + to define the first outcome.','muted'));
  for(const t of state.tasks){const b=node('button',undefined,'task-item'+(selectedTask===t.id?' active':''));b.append(node('strong',t.id),node('small',t.status));b.onclick=()=>{selectedTask=t.id;renderTasks();renderInspector();};$('task-list').append(b);}
  $('accepted-count').textContent=state.metrics.accepted??0;$('failure-count').textContent=state.failures.reduce((n,f)=>n+f.occurrences,0);
}
function renderInspector(){
  const t=task(),term=terminal(),linked=term&&term.task===selectedTask;
  $('task-status').textContent=t?t.status.toUpperCase():'UNASSIGNED';
  $('task-title').textContent=t?t.id:'Keep the objective close.';
  $('task-objective').textContent=t?t.objective:'Select a task from the queue, then open a terminal assigned to it.';
  $('task-acceptance').textContent=t?t.acceptance:'Define what a successful result must demonstrate.';
  const sessions=state.sessions.filter(s=>s.task_id===selectedTask);
  $('token-usage').textContent=t?`${sessions.reduce((n,s)=>n+s.tokens,0).toLocaleString()} reported / ${t.token_budget.toLocaleString()} budget`:'Unknown until checkpointed';
  const current=linked?state.sessions.find(s=>s.id===term.session):null;
  $('checkpoint').disabled=!current||current.status!=='active';
  $('fail').disabled=!current||current.status!=='active';
  $('finish').disabled=!current||current.status!=='active'||term.state==='running';
  $('accept').disabled=!t||t.status!=='review';
  $('retry').disabled=!t||!['blocked','review'].includes(t.status);
  $('pack').disabled=!t;
  $('next-step').textContent=!t?'No checkpoint yet.':current?.status==='active'?'Record evidence and a next step before the ownership lease expires.':'Inspect the context packet for the latest handoff.';
}
function renderFailures(){
  const list=$('failure-list');list.replaceChildren();
  if(!state.failures.length){list.append(node('p','No failures recorded.','muted'));return;}
  for(const f of state.failures){const row=node('div',undefined,'failure-row');row.append(node('small',`${f.occurrences} occurrence${f.occurrences===1?'':'s'}`),node('strong',f.category),node('p',f.summary),node('code',f.fingerprint));list.append(row);}
}
function showView(view){for(const name of ['workspace','failures','tools']){$(name+'-view').hidden=name!==view;$(name+'-nav').classList.toggle('selected',name===view);} $('view-title').textContent={workspace:'Workspace',failures:'Failure ledger',tools:'Tool catalog'}[view];if(view==='workspace'&&terminal())requestAnimationFrame(()=>terminal().fit.fit());}
for(const view of ['workspace','failures','tools'])$(view+'-nav').onclick=()=>showView(view);
function renderTabs(){
  $('tabs').replaceChildren();for(const t of terms.values()){const b=node('button',`${t.state==='running'?'●':'○'} ${t.task||'Shell'} ${t.ordinal}`, 'tab'+(t.id===activeTerminal?' active':''));b.onclick=()=>activate(t.id);$('tabs').append(b);}
  $('terminal-empty').hidden=terms.size>0;
}
function activate(id){activeTerminal=id;const t=terms.get(id);if(t.task)selectedTask=t.task;
  for(const other of terms.values())other.el.classList.toggle('active',other.id===id);
  $('terminal-path').textContent=t.cwd;$('terminal-state').textContent=t.state==='running'?'SHELL ACTIVE':`EXITED · ${t.exitCode??'—'}`;
  $('terminal-hint').textContent=t.session?'Linked to a ledger session. Shell activity is not verified progress.':'Unassigned shell · no task completion inferred.';
  $('stop-terminal').disabled=t.state!=='running';$('remove-terminal').disabled=t.state==='running';renderTabs();renderTasks();renderInspector();
  requestAnimationFrame(()=>{t.fit.fit();t.xterm.focus();});
}
function receive(p){const t=terms.get(p.id);if(!t){const q=pending.get(p.id)||[];q.push(p);if(q.length>32)q.shift();pending.set(p.id,q);return;}if(p.seq<=t.seq)return;t.seq=p.seq;t.xterm.write(p.data);}
function addTerminal(info){
  const el=node('div',undefined,'terminal-pane');$('terminal-area').append(el);
  const xterm=new Terminal({cursorBlink:true,fontSize:12,fontFamily:'"SFMono-Regular", Menlo, monospace',scrollback:3000,allowProposedApi:false,theme:{background:'#10191e',foreground:'#d1e1dc',cursor:'#79d3b4',selectionBackground:'#305d52'}});
  const fit=new FitAddon.FitAddon();xterm.loadAddon(fit);xterm.open(el);
  // Never accept terminal-initiated clipboard writes or external links.
  xterm.parser.registerOscHandler(52,()=>true);
  xterm.onData(data=>api.write(info.id,data).catch(error));
  xterm.onResize(({cols,rows})=>api.resize(info.id,cols,rows).catch(error));
  const t={...info,xterm,fit,el,seq:0,ordinal:terms.size+1};terms.set(info.id,t);
  for(const chunk of info.chunks||[])receive({id:info.id,...chunk});
  for(const chunk of pending.get(info.id)||[])receive(chunk);pending.delete(info.id);
  new ResizeObserver(()=>{if(t.id===activeTerminal&&el.offsetWidth>0)fit.fit();}).observe(el);
  activate(info.id);
}
api.onData(receive);
api.onExit(({id,exitCode})=>{const t=terms.get(id);if(!t)return;t.state='exited';t.exitCode=exitCode;t.xterm.writeln(`\r\n[Shell exited with code ${exitCode}. Task acceptance is unchanged.]`);if(activeTerminal===id)activate(id);else renderTabs();refresh();});
$('add-task').onclick=()=>$('task-dialog').showModal();
$('task-form').onsubmit=safe(async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));await api.ledger('create',data);selectedTask=data.id;$('task-dialog').close();e.target.reset();await refresh();});
let launchTool=null, toolRows=[];
function openTerminal(tool=null){
  launchTool=typeof tool==='string'?tool:null;
  $('launch-tool').textContent=launchTool?`Launch ${launchTool} directly, with no added arguments. Existing account settings apply.`:'Open your login shell.';
  $('cwd').value=home;const select=$('terminal-task');select.replaceChildren(new Option('Unassigned shell',''));
  for(const t of state.tasks.filter(t=>t.status==='ready'))select.add(new Option(t.id,t.id));
  if(task()?.status==='ready')select.value=selectedTask;
  $('terminal-dialog').showModal();
}
$('new-terminal').onclick=openTerminal;$('empty-new').onclick=openTerminal;
$('choose-folder').onclick=safe(async()=>{const folder=await api.chooseDirectory();if(folder)$('cwd').value=folder;});
$('terminal-form').onsubmit=safe(async e=>{e.preventDefault();const button=e.target.querySelector('button.primary');button.disabled=true;try{const info=await api.createTerminal({cwd:$('cwd').value,task:$('terminal-task').value||null,tool:launchTool});$('terminal-dialog').close();showView('workspace');addTerminal(info);await refresh();}finally{button.disabled=false;}});
$('stop-terminal').onclick=safe(async()=>{if(terminal())await api.stop(activeTerminal);});
$('remove-terminal').onclick=safe(async()=>{const t=terminal();if(!t)return;await api.remove(t.id);t.xterm.dispose();t.el.remove();terms.delete(t.id);if(terms.size)activate(terms.keys().next().value);else{activeTerminal=null;renderTabs();$('terminal-path').textContent='Choose a folder to begin';$('terminal-state').textContent='NO SHELL RUNNING';$('stop-terminal').disabled=true;$('remove-terminal').disabled=true;renderInspector();}});
const definitions={checkpoint:['Record checkpoint',['summary','evidence','next','tokens']],fail:['Record failure',['category','summary']],finish:['Submit for review',['evidence']],accept:['Accept result',['reason']],retry:['Retry after reconciliation',['reason']]};
for(const name of Object.keys(definitions))$(name).onclick=()=>{
  action={name,task:selectedTask,session:terminal()?.session};const [title,fields]=definitions[name];$('action-title').textContent=title;$('action-fields').replaceChildren();
  for(const field of fields){const label=node('label',{summary:'What changed',evidence:'Evidence or artifact reference',next:'Next step',tokens:'Cumulative session tokens (reported)',category:'Failure category',reason:'Reason and reconciliation evidence'}[field]);const input=node(['summary','evidence','next','reason'].includes(field)?'textarea':'input');input.name=field;input.required=true;if(field==='tokens'){input.type='number';input.min='0';input.value=state.sessions.find(s=>s.id===action.session)?.tokens??0;}label.append(input);$('action-fields').append(label);}
  $('action-dialog').showModal();
};
$('action-form').onsubmit=safe(async e=>{e.preventDefault();const data={...Object.fromEntries(new FormData(e.target)),task:action.task,session:action.session};if('tokens'in data)data.tokens=Number(data.tokens);await api.ledger(action.name,data);$('action-dialog').close();await refresh();});
$('pack').onclick=safe(async()=>{const result=await api.ledger('pack',{task:selectedTask});$('packet').textContent=JSON.stringify(result,null,2);$('packet-dialog').showModal();});
for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>b.closest('dialog').close();
// Global navigation avoids intercepting ordinary terminal keys.
document.addEventListener('keydown',e=>{if(e.metaKey&&e.shiftKey&&e.key.toLowerCase()==='t'){e.preventDefault();openTerminal();}});
(async()=>{try{const initial=await api.bootstrap();home=initial.home;for(const t of initial.terminals)addTerminal(t);await refresh();}catch(e){error(e);}})();
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
