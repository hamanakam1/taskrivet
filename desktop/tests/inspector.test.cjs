const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

// Run the real renderer with synthetic DOM and bridge objects. No Electron,
// terminal process, ledger, network connection, or third-party package is used.
class Element {
  constructor(tag='div') {
    this.tagName=tag.toUpperCase();this.children=[];this.hidden=false;
    this.disabled=false;this.value='';this.dataset={};this.style={};this._text='';
    const classes=new Set();
    this.classList={toggle:(name,on)=>{if(on)classes.add(name);else classes.delete(name);},contains:name=>classes.has(name)};
  }
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this._text='';this.children=children;}
  addEventListener(){}
  setAttribute(){}
  remove(){this.removed=true;}
  focus(){}
  querySelector(){return null;}
}
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
async function settle(){await new Promise(resolve=>setImmediate(resolve));}
function task(id){return {id,objective:`Objective ${id}`,acceptance:`Acceptance ${id}`,kind:'code',scope:[`fixture/${id}`],status:'running',token_budget:100,created:1};}
function view(id,session=`session-${id}`,evidence=`Evidence ${id}`){
  const current={id:session,task_id:id,status:'active',owner:`Owner ${id}`,tokens:10,created:1,lease_remaining_seconds:100};
  return {task:{...task(id),reported_tokens:10},session:current,sessions:[current],context:[],
    checkpoints:[{summary:`Summary ${id}`,evidence,next_step:'Review',tokens:10,created:1}],
    failures:[],events:[],claims:[],pack:{bytes:100,items:0,omitted:[],error:null}};
}
async function renderer(){
  const elements=new Map(),requests=[];
  const element=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const bridge={
    bootstrap:async()=>({home:'/synthetic',terminals:[]}),
    ledger:async(action,data)=>{
      if(action==='status')return {tasks:['alpha','beta'].map(task),sessions:[],failures:[],metrics:{accepted:0}};
      if(action==='detail'){const request={...deferred(),data};requests.push(request);return request.promise;}
      throw new Error(`Unexpected ledger operation: ${action}`);
    },
    onData(){},onDisconnect(){},onExit(){},onIntegrationError(){},
    remove:async()=>{},stop:async()=>{throw new Error('No real terminal should be stopped');},
  };
  const context=vm.createContext({
    window:{workspace:bridge},document:{getElementById:element,createElement:tag=>new Element(tag),
      querySelector:()=>null,querySelectorAll:()=>[],addEventListener(){},body:new Element()},
    localStorage:{getItem:()=>null},setInterval(){},requestAnimationFrame(){},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/app.js'),'utf8'),context);
  await settle();
  const run=code=>vm.runInContext(code,context);
  const clickTask=id=>{
    const button=element('task-list').children.find(child=>child.children[0]?.textContent===id);
    assert.ok(button,`Task ${id} is rendered`);button.onclick();
  };
  const addPane=(id,taskId,session,tabId)=>{
    context.fixturePane={id,task:taskId,session,state:'exited',cwd:'/synthetic',shell:'/bin/sh',
      el:new Element(),xterm:{dispose(){},focus(){}},fit:{fit(){}}};
    context.fixtureTab={id:tabId,title:null,panes:[id],tree:{type:'leaf',id},container:new Element()};
    run(`{ terms.set(fixturePane.id,fixturePane); const existingTab=tabs.find(t=>t.id===fixtureTab.id);
      if(existingTab){existingTab.panes.push(fixturePane.id);existingTab.tree={type:'split',dir:'h',children:[existingTab.tree,{type:'leaf',id:fixturePane.id}]};}
      else tabs.push(fixtureTab); }`);
  };
  return {element,requests,run,clickTask,addPane};
}
async function loadTask(ui,id){
  ui.clickTask(id);
  // Explicit refresh also makes setup work on the old renderer, so each test's
  // assertion exercises the regression rather than depending on setup failure.
  ui.run('loadDetail(true).then(renderInspector)');
  const request=ui.requests.at(-1);request.resolve(view(id));await settle();
}

test('task selection clears old evidence immediately and requests its own detail',async()=>{
  const ui=await renderer();await loadTask(ui,'alpha');
  assert.match(ui.element('insp-checkpoints').textContent,/Evidence alpha/);
  const before=ui.requests.length;ui.clickTask('beta');
  assert.equal(ui.element('session-title').textContent,'beta');
  assert.equal(ui.element('insp-checkpoints-block').hidden,true);
  assert.equal(ui.element('checkpoint').disabled,true);
  assert.equal(ui.requests.length,before+1);
  assert.equal(ui.requests.at(-1).data.task,'beta');
  ui.requests.at(-1).resolve(view('beta'));await settle();
  assert.match(ui.element('insp-checkpoints').textContent,/Evidence beta/);
  assert.doesNotMatch(ui.element('insp-session').textContent,/Owner alpha/);
});

for(const outcome of ['success','failure'])test(`an old detail ${outcome} cannot replace the newly selected task`,async()=>{
  const ui=await renderer();await loadTask(ui,'alpha');
  ui.run('loadDetail(true).then(renderInspector)');const old=ui.requests.at(-1);
  ui.clickTask('beta');ui.run('loadDetail(true).then(renderInspector)');
  ui.requests.at(-1).resolve(view('beta'));await settle();
  if(outcome==='success')old.resolve(view('alpha'));else old.reject(new Error('Old request failed'));
  await settle();
  assert.equal(ui.element('session-title').textContent,'beta');
  assert.match(ui.element('insp-session').textContent,/Owner beta/);
  assert.match(ui.element('insp-checkpoints').textContent,/Evidence beta/);
  assert.equal(ui.element('checkpoint').disabled,false);
});

test('the newest forced refresh wins even for the same task and session',async()=>{
  const ui=await renderer();await loadTask(ui,'alpha');
  ui.run('loadDetail(true).then(renderInspector)');const older=ui.requests.at(-1);
  ui.run('loadDetail(true).then(renderInspector)');const newer=ui.requests.at(-1);
  newer.resolve(view('alpha','session-alpha','Newest evidence'));await settle();
  older.resolve(view('alpha','session-alpha','Obsolete evidence'));await settle();
  assert.match(ui.element('insp-checkpoints').textContent,/Newest evidence/);
  assert.doesNotMatch(ui.element('insp-checkpoints').textContent,/Obsolete evidence/);
});

test('tab and pane focus reload the focused attempt and preserve pane precedence',async()=>{
  const ui=await renderer();await loadTask(ui,'alpha');
  ui.addPane('pane-alpha','alpha','attempt-alpha','tab-alpha');
  ui.addPane('pane-beta','beta','attempt-beta','tab-beta');
  ui.run("activateTab('tab-beta')");
  assert.equal(ui.element('session-title').textContent,'beta');
  assert.equal(ui.element('checkpoint').disabled,true);
  assert.equal(ui.requests.at(-1).data.session,'attempt-beta');
  ui.requests.at(-1).resolve(view('beta','attempt-beta'));await settle();
  ui.clickTask('alpha');
  assert.equal(ui.element('session-title').textContent,'beta');
  assert.equal(ui.requests.at(-1).data.task,'beta');
  ui.run("activatePane('pane-alpha')");
  assert.equal(ui.element('session-title').textContent,'alpha');
  assert.equal(ui.element('checkpoint').disabled,true);
  assert.equal(ui.requests.at(-1).data.session,'attempt-alpha');
  ui.requests.at(-1).resolve(view('alpha','attempt-alpha'));await settle();
  assert.match(ui.element('insp-session').textContent,/attempt-alpha/);
});

test('closing focused panes and tabs loads the replacement focus',async()=>{
  const ui=await renderer();
  ui.addPane('pane-alpha','alpha','attempt-alpha','tab-shared');
  ui.addPane('pane-beta','beta','attempt-beta','tab-shared');
  ui.addPane('pane-other','alpha','attempt-other','tab-other');
  ui.run("activateTab('tab-shared'); activatePane('pane-beta')");
  ui.requests.at(-1).resolve(view('beta','attempt-beta'));await settle();
  await ui.run("closePane('pane-beta')");
  assert.equal(ui.element('session-title').textContent,'alpha');
  assert.equal(ui.element('checkpoint').disabled,true);
  assert.equal(ui.requests.at(-1).data.session,'attempt-alpha');
  ui.requests.at(-1).resolve(view('alpha','attempt-alpha'));await settle();
  await ui.run("closeTab('tab-shared')");
  assert.equal(ui.element('checkpoint').disabled,true);
  assert.equal(ui.requests.at(-1).data.session,'attempt-other');
  ui.requests.at(-1).resolve(view('alpha','attempt-other'));await settle();
  assert.match(ui.element('insp-session').textContent,/attempt-other/);
});
