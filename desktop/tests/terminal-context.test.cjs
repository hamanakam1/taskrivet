const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');

// Exercise the actual renderer submit handler with DOM and IPC doubles.
// No application, shell, ledger, or service is started by these checks.
function form({inherit=false,status='running',hasSession=true}={}){
  const source=fs.readFileSync(path.join(__dirname,'../ui/app.js'),'utf8');
  const start=source.indexOf("$('terminal-form').onsubmit=");
  const end=source.indexOf("$('stop-terminal').onclick=",start);
  assert.ok(start>=0&&end>start,'terminal form handler must exist');
  const button={disabled:false},calls=[];
  const elements={
    'terminal-form':{},'terminal-task':{value:'demo-task'},
    'inherit-ticket-context':{checked:inherit},cwd:{value:'/tmp/synthetic'},
    'terminal-dialog':{close(){}},
  };
  const context={
    $:id=>elements[id],safe:fn=>fn,launchTool:'demo-agent',
    state:{tasks:[{id:'demo-task',status}],sessions:hasSession?[{id:'demo-session',task_id:'demo-task',status:'active'}]:[]},
    api:{createTerminal:async request=>{calls.push(JSON.parse(JSON.stringify(request)));return {id:'demo-terminal'};}},
    showView(){},addTerminal(){},refresh:async()=>{},
  };
  vm.runInNewContext(source.slice(start,end),context,{filename:'app.js:terminal-form'});
  return {calls,button,submit:()=>elements['terminal-form'].onsubmit({preventDefault(){},target:{querySelector:()=>button}})};
}

test('unchecked context opens standalone even when a task is selected',async()=>{
  for(const status of ['ready','running']){
    const fixture=form({status});
    await fixture.submit();
    assert.deepEqual(fixture.calls,[{cwd:'/tmp/synthetic',task:null,session:null,tool:'demo-agent'}]);
    assert.equal(fixture.button.disabled,false);
  }
});

test('checked context joins the selected active session explicitly',async()=>{
  const fixture=form({inherit:true});
  await fixture.submit();
  assert.deepEqual(fixture.calls,[{cwd:'/tmp/synthetic',task:'demo-task',session:'demo-session',tool:'demo-agent'}]);
});

test('checked context refuses a missing or inactive attempt before launch',async()=>{
  for(const options of [{status:'ready'},{hasSession:false}]){
    const fixture=form({inherit:true,...options});
    await assert.rejects(fixture.submit(),/Active ticket context is unavailable/);
    assert.deepEqual(fixture.calls,[]);
    assert.equal(fixture.button.disabled,false);
  }
});
