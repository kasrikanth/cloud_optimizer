import {validateImport} from './utils.js';
import {api,auth} from './api.js';
import {esc,money,icon,badge,metric,sum,lineChart} from './ui.js';
import {table,metrics,confidenceNote,dashboardView,askPanel,accountsView,acctPager,addAccountForm,editAccountForm,credentialFields,MODES_BY_PROVIDER,idLabel,compareView,servicesView,assetsTable,monitorView,savingsView,organizationView,reportView,aiError,aiAssistHtml} from './views.js';
const $=s=>document.querySelector(s);
const initial=()=>({resources:[],findings:[],log:[],lastScan:null,accounts:{accounts:[]},dashboard:null,org:null,comparison:null,monitor:null,forecast:null,services:null});
const svcFilters={service:'all',account:'all',q:''};
let state=initial(),authenticated=false,busy=false,chat=null,showAllLog=false;
let page='overview', filters={search:'',provider:'All clouds',account:'all',status:'All statuses',risk:'All risks',kind:'All types'},lastFocus=null,toastTimer,monitorTimer;
const monitorUi={severity:'all',opened:new Set(),updated:new Date(),llm:false,diagnosis:null,anomalies:{},busy:''};
let reportAi={result:null,busy:false},forecastAi={result:null,busy:false},forecastLoading=false;
const rows=()=>state.findings;
const recs=()=>rows().filter(r=>r.kind!=='Healthy');
const pending=()=>recs().filter(r=>r.status==='Pending');
const approved=()=>recs().filter(r=>r.status==='Approved');
const accountName=id=>state.accounts.accounts.find(a=>a.id===id)?.name||'';
const hasData=()=>state.resources.length||state.accounts.accounts.some(a=>a.id);
async function load(){const [ws,accounts,dashboard,org]=await Promise.all([api.workspace(),api.accounts(),api.dashboard(),api.organization()]);state={...ws,accounts,dashboard,org,comparison:null,monitor:null,forecast:null,services:null};authenticated=true;render();}
function signOut(message=''){clearInterval(monitorTimer);auth.clear();state=initial();chat=null;closeDrawer();showLogin(message);}
// fn may return a string to replace the default success message.
async function run(fn,message){
 if(busy)return toast('Please wait for the current request.');
 busy=true;document.body.classList.add('working');
 try{const result=await fn();await load();const text=typeof result==='string'?result:message;if(text)toast(text);}
 catch(error){if(error.status===401)signOut(error.message);else{if(error.status===409)await load().catch(()=>{});toast(error.message);}}
 finally{busy=false;document.body.classList.remove('working');}
}
function setHeading(title,subtitle){$('#title').textContent=title;$('#subtitle').textContent=subtitle;$('#crumb').textContent=title;}
function toast(t){clearTimeout(toastTimer);$('#toast').textContent=t;$('#toast').style.display='block';toastTimer=setTimeout(()=>$('#toast').style.display='none',t.length>70?9000:4500);}

// ------------------------------------------------------------------ sign in
function showLogin(message='',mode='login',email=''){
 authenticated=false;document.body.classList.add('signed-out');
 setHeading(mode==='login'?'Sign in':'Create an organization','');$('#heading-actions').innerHTML='';$('#navigation').innerHTML='';
 const signup=mode==='signup';
 $('#view').innerHTML=`<div class="login-brand">stratus</div><div class="panel login-panel">${signup
  ?`<h2>Create an organization</h2><p>Each organization has its own cloud accounts, data and members. You become its admin.</p><form id="auth-form" novalidate><label for="org">Organization name</label><input id="org" required minlength="2" maxlength="80" autocomplete="organization" placeholder="Acme Corp"><label for="email">Work email</label><input id="email" type="email" autocomplete="email" required placeholder="you@company.com" value="${esc(email)}"><label for="password">Password</label><input id="password" type="password" autocomplete="new-password" required minlength="8" placeholder="At least 8 characters"><button class="btn primary" type="submit">Create organization</button><p class="form-error" id="login-error" role="alert"></p></form><button class="text-button" id="switch-mode" type="button">Already have an account? Sign in</button>`
  :`<h2>Sign in to your organization</h2><p>Use the email and password for your organization account.</p><form id="auth-form" novalidate><label for="email">Work email</label><input id="email" type="email" autocomplete="email" required placeholder="you@company.com" value="${esc(email)}"><label for="password">Password</label><input id="password" type="password" autocomplete="current-password" required><button class="btn primary" type="submit">Sign in</button><p class="form-error" id="login-error" role="alert"></p></form><button class="text-button" id="switch-mode" type="button">New here? Create an organization</button>`}</div>`;
 $('#login-error').textContent=message;
 $('#switch-mode').onclick=()=>showLogin('',signup?'login':'signup',$('#email').value.trim());
 $(signup?'#org':'#email').focus();
 $('#auth-form').onsubmit=async e=>{
  e.preventDefault();const btn=$('#auth-form button[type=submit]'),email=$('#email').value.trim().toLowerCase(),password=$('#password').value,error=$('#login-error');
  if(!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)){error.textContent='Enter a valid email address.';return;}
  if(signup&&password.length<8){error.textContent='Password must be at least 8 characters.';return;}
  const label=btn.textContent;btn.disabled=true;btn.classList.add('loading');btn.innerHTML=`<span class="spinner" aria-hidden="true"></span>${signup?'Creating…':'Signing in…'}`;error.textContent='';
  try{const r=signup?await api.signup({organization:$('#org').value.trim(),email,password}):await api.login(email,password);auth.set(r.token,r.user.email);await load();}
  catch(err){auth.clear();error.textContent=err.message;btn.disabled=false;btn.classList.remove('loading');btn.textContent=label;}
 };
}

// -------------------------------------------------------------------- pages
const TITLES={overview:['Dashboard'],opportunities:['Opportunities'],savings:['Savings'],accounts:['Cloud accounts'],services:['Services'],compare:['Compare services'],monitor:['Monitor'],organization:['Organization'],report:['Executive report','A one-page summary to share with leadership.'],guide:['Integration guide','How inventory reaches the optimizer.']};
// Old routes still work: they land on the screen the content moved to.
const ALIASES={approvals:'opportunities',activity:'organization',integrations:'accounts','compare-inventory':'compare','compare-pricing':'compare','monitor-accounts':'monitor','monitor-pipeline':'monitor'};
const ROUTE_NAV={report:'overview',guide:'accounts'};
// The four product features are the top level. Features with two screens are branches; the rest are single screens.
const TREE=[
 {id:'optimizer',label:'Cloud Optimizer',icon:'opportunities',items:[['opportunities','Opportunities'],['savings','Savings']]},
 {id:'dashboard',label:'Multi-cloud Dashboard',icon:'overview',items:[['overview','Overview'],['accounts','Cloud accounts'],['services','Services']]},
 {id:'compare',label:'Cloud Service Comparison',icon:'compare',page:'compare'},
 {id:'monitor',label:'Troubleshooter / Monitor',icon:'monitor',page:'monitor'},
 {id:'organization',label:'Organization',icon:'organization',page:'organization'}];
const SUB_ICON={services:'integrations'};
let pageSize=10,oppPage=1;
const NAV_KEY='stratus-nav-collapsed';
const navPage=p=>ROUTE_NAV[p]||p;
const groupOf=p=>TREE.find(g=>g.page===navPage(p)||g.items?.some(([id])=>id===navPage(p)));
function collapsed(){try{return new Set(JSON.parse(localStorage.getItem(NAV_KEY)||'[]'));}catch{return new Set();}}
function saveCollapsed(set){try{localStorage.setItem(NAV_KEY,JSON.stringify([...set]));}catch{}}
function renderNav(){
 const shut=collapsed(),current=groupOf(page)?.id;
 $('#navigation').innerHTML=TREE.map(g=>{
  if(g.page)return `<div class="nav-group"><a class="nav-group-head leaf ${g.id===current?'current':''}" href="#${g.page}" ${g.id===current?'aria-current="page"':''}>${icon(g.icon)}<span class="nav-text">${g.label}</span></a></div>`;
  const open=g.id===current||!shut.has(g.id);
  return `<div class="nav-group"><button type="button" class="nav-group-head ${g.id===current?'current':''}" data-group="${g.id}" aria-expanded="${open}" aria-controls="nav-${g.id}">${icon(g.icon)}<span class="nav-text">${g.label}</span><svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></button><div class="nav-children" id="nav-${g.id}" ${open?'':'hidden'}>${g.items.map(([id,label])=>`<a href="#${id}" class="${navPage(page)===id?'active':''}" ${navPage(page)===id?'aria-current="page"':''}>${icon(SUB_ICON[id]||id)}<span class="nav-text">${label}</span>${id==='opportunities'&&pending().length?`<span class="count">${pending().length}</span>`:''}</a>`).join('')}</div></div>`;
 }).join('');
 document.querySelectorAll('button.nav-group-head').forEach(b=>b.onclick=()=>{
  const open=b.getAttribute('aria-expanded')==='true',set=collapsed();
  b.setAttribute('aria-expanded',String(!open));$('#'+b.getAttribute('aria-controls')).hidden=open;
  open?set.add(b.dataset.group):set.delete(b.dataset.group);saveCollapsed(set);});
 document.querySelectorAll('#navigation a').forEach(a=>a.onclick=()=>document.body.classList.remove('nav-open'));
}
// The forecast loads quietly after the dashboard paints; a failure just leaves the panel out.
function ensureForecast(){
 if(state.forecast||forecastLoading||!hasData())return;
 forecastLoading=true;
 api.forecast().then(d=>{state.forecast=d;}).catch(e=>{if(e.status===401)return signOut(e.message);state.forecast={error:true};})
  .finally(()=>{forecastLoading=false;if(authenticated&&page==='overview'&&state.forecast)render();});
}
function loading(){return '<div class="panel empty"><p>Loading…</p></div>';}
function fetchInto(key,fn,then){if(state[key])return false;$('#view').innerHTML=loading();fn().then(d=>{state[key]=d;if(authenticated&&then())render();}).catch(e=>e.status===401?signOut(e.message):toast(e.message));return true;}
function render(){
 if(!authenticated)return showLogin();
 document.body.classList.remove('signed-out');$('#user-email').textContent=auth.email();$('#org-name').textContent=state.org?.name||'';
 clearInterval(monitorTimer);
 page=location.hash.slice(1)||'overview';
 if(ALIASES[page]){if(page==='approvals')filters.status='Approved';page=ALIASES[page];history.replaceState(null,'','#'+page);}
 if(!TITLES[page])page='overview';
 setHeading(...TITLES[page]);
 renderNav();
 {const g=groupOf(page),item=g?.items?.find(([id])=>id===navPage(page));$('#crumb').textContent=g?(item?`${g.label} / ${item[1]}`:g.label):TITLES[page][0];}
 const exportBtn=`<button class="btn" id="export">${icon('download')} Export CSV</button>`,scanBtn=`<button class="btn primary" id="scan">${icon('scan')} Run analysis</button>`;
 const actions={overview:`<a class="btn" href="#report">${icon('report')} Executive report</a>${exportBtn}${scanBtn}`,opportunities:exportBtn+scanBtn,accounts:`<button class="btn" id="sync-all">${icon('scan')} Sync all</button><button class="btn primary" data-add-account>${icon('plus')} Add cloud account</button>`,monitor:`<button class="btn" id="refresh-monitor">${icon('scan')} Refresh now</button>`}[page];
 $('#heading-actions').innerHTML=actions?`<div class="actions">${actions}</div>${['overview','opportunities'].includes(page)&&state.lastScan?`<div class="heading-note">Last analyzed ${new Date(state.lastScan).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</div>`:''}`:'';
 const view=$('#view');
 if(page==='overview')view.innerHTML=hasData()?dashboardView(state,chat,forecastAi):`<div class="panel empty"><h3>Connect your first cloud account</h3><p>Add an account, or start with a demo account that needs no credentials.</p><div class="actions" style="justify-content:center"><button class="btn primary" data-add-account>${icon('plus')} Add cloud account</button><button class="btn" id="load-sample">Load sample inventory</button></div></div>`;
 if(page==='opportunities'){
  const accountOptions=[['all','All accounts'],...state.accounts.accounts.map(a=>[a.id||'none',a.name])];
  view.innerHTML=metrics(state)+`<div class="panel"><div class="filters"><input id="search" aria-label="Search resources or owners" placeholder="Search resources or owners" value="${esc(filters.search)}"><select id="account" aria-label="Filter account">${accountOptions.map(([v,l])=>`<option value="${esc(v)}" ${filters.account===v?'selected':''}>${esc(l)}</option>`).join('')}</select><select id="status" aria-label="Filter status">${['All statuses','Pending','Approved','Simulated','Implemented','Dismissed'].map(x=>`<option ${filters.status===x?'selected':''}>${x}</option>`).join('')}</select><select id="provider" aria-label="Filter cloud">${['All clouds','AWS','Azure','GCP'].map(x=>`<option ${filters.provider===x?'selected':''}>${x}</option>`).join('')}</select><select id="risk" aria-label="Filter risk">${['All risks','Low','Medium','High','Review'].map(x=>`<option ${filters.risk===x?'selected':''}>${x}</option>`).join('')}</select><select id="kind" aria-label="Filter opportunity type">${['All types','Idle resource','Oversized resource','After-hours usage','Review telemetry'].map(x=>`<option ${filters.kind===x?'selected':''}>${x}</option>`).join('')}</select></div><div id="filtered-table"></div></div>`;filterTable();}
 if(page==='savings')view.innerHTML=savingsView(state);
 if(page==='accounts')view.innerHTML=accountsView(state);
 if(page==='services'&&!fetchInto('services',api.cloudServices,()=>page==='services'))view.innerHTML=servicesView(state.services,svcFilters);
 if(page.startsWith('compare')&&!fetchInto('comparison',api.comparison,()=>page.startsWith('compare')))view.innerHTML=compareView(state.comparison);
 if(page==='report'&&!fetchInto('monitor',api.monitor,()=>page==='report'))view.innerHTML=reportView(state,state.monitor,reportAi);
 if(page.startsWith('monitor')){if(state.monitor){renderMonitor();monitorTimer=setInterval(refreshMonitor,30000);}else{view.innerHTML=loading();refreshMonitor(true);monitorTimer=setInterval(refreshMonitor,30000);}}
 if(page==='organization')view.innerHTML=organizationView(state,{allLog:showAllLog});
 if(page==='guide')view.innerHTML=guide();
 bind();
 if(page==='overview')ensureForecast();
}
function renderMonitor(){
 monitorUi.llm=!!state.org?.llmConfigured;
 $('#view').innerHTML=monitorView(state.monitor,monitorUi);const sel=$('#severity');if(sel)sel.onchange=e=>{monitorUi.severity=e.target.value;renderMonitor();};
 if($('#ai-diagnose'))$('#ai-diagnose').onclick=()=>aiCall(()=>api.aiMonitor(),r=>{monitorUi.diagnosis=r;},v=>{monitorUi.busy=v?'diagnose':'';},renderMonitor);
 document.querySelectorAll('[data-ai-anomaly]').forEach(b=>b.onclick=()=>{const id=b.dataset.aiAnomaly;aiCall(()=>api.aiAnomaly(id),r=>{monitorUi.anomalies[id]=r;monitorUi.opened.add(b.closest('details')?.dataset.issue);},v=>{monitorUi.busy=v?'anomaly:'+id:'';},renderMonitor);});
}
// Runs one AI request. Errors are shown in place of the result; a 401 signs out. set(result|{error}), busy(bool), redraw().
async function aiCall(fn,set,busy,redraw){
 busy(true);redraw();
 try{set(await fn());}
 catch(e){if(e.status===401)return signOut(e.message);set({error:e.message});}
 finally{busy(false);}
 if(authenticated)redraw();
}
async function refreshMonitor(force=false){
 if(!authenticated||(!force&&document.hidden))return;
 try{state.monitor=await api.monitor();monitorUi.updated=new Date();if(page.startsWith('monitor'))renderMonitor();}
 catch(e){if(e.status===401)signOut(e.message);else if(force)toast(e.message);}
}
function filterTable(){const q=filters.search.toLowerCase();const list=recs().filter(r=>(filters.provider==='All clouds'||r.provider===filters.provider)&&(filters.account==='all'||(filters.account==='none'?!r.accountId:r.accountId===filters.account))&&(filters.status==='All statuses'||r.status===filters.status)&&(filters.risk==='All risks'||r.risk===filters.risk)&&(filters.kind==='All types'||r.kind===filters.kind)&&[r.name,r.owner,r.id].join(' ').toLowerCase().includes(q));const pages=Math.max(1,Math.ceil(list.length/pageSize));oppPage=Math.min(oppPage,pages);const from=(oppPage-1)*pageSize,shown=list.slice(from,from+pageSize);$('#filtered-table').innerHTML=table(state,shown,true)+`<div class="table-foot"><span>${list.length?`Showing ${from+1}–${from+shown.length} of ${list.length}`:'0'} match your filters · ${state.resources.length} resources analyzed</span><div class="pager"><label class="page-size">Rows per page <select id="page-size" aria-label="Rows per page">${[5,10,15].map(n=>`<option ${n===pageSize?'selected':''}>${n}</option>`).join('')}</select></label><button class="btn" type="button" data-page="prev" ${oppPage<=1?'disabled':''}>Previous</button><span>Page ${oppPage} of ${pages}</span><button class="btn" type="button" data-page="next" ${oppPage>=pages?'disabled':''}>Next</button></div></div>`;$('#page-size').onchange=e=>{pageSize=+e.target.value;oppPage=1;filterTable();};document.querySelectorAll('#filtered-table [data-page]').forEach(b=>b.onclick=()=>{oppPage+=b.dataset.page==='next'?1:-1;filterTable();});bindDetails();}
function bindDetails(){document.querySelectorAll('[data-detail]').forEach(b=>b.onclick=()=>openDetail(b.dataset.detail));}
async function ask(question){
 chat={question,result:null,busy:true};rerenderAsk();
 try{chat.result=await api.ask(question);}catch(e){if(e.status===401)return signOut(e.message);toast(e.message);}
 finally{if(chat)chat.busy=false;}
 rerenderAsk();
}
function rerenderAsk(){const panel=document.querySelector('.ask');if(!panel)return;panel.outerHTML=askPanel(chat);bindAsk();}
function bindAsk(){
 const form=$('#ask-form');if(form)form.onsubmit=e=>{e.preventDefault();const q=$('#ask-input').value.trim();if(q.length>1)ask(q);};
 document.querySelectorAll('[data-ask]').forEach(b=>b.onclick=()=>ask(b.dataset.ask));
}
function bind(){
 bindDetails();bindAsk();
 for(const [id,key] of [['svc-q','q'],['svc-service','service'],['svc-account','account']])if($('#'+id))$('#'+id)[key==='q'?'oninput':'onchange']=e=>{svcFilters[key]=e.target.value;$('#assets-table').innerHTML=assetsTable(state.services,svcFilters);};
 if($('#scan'))$('#scan').onclick=()=>run(()=>api.scan(),'Analysis complete.');
 if($('#export'))$('#export').onclick=exportReport;
 if($('#print-report'))$('#print-report').onclick=()=>window.print();
 if($('#ai-forecast'))$('#ai-forecast').onclick=()=>aiCall(()=>api.aiForecast(),r=>{forecastAi.result=r;},v=>{forecastAi.busy=v;},render);
 if($('#ai-report'))$('#ai-report').onclick=()=>aiCall(()=>api.aiReport(),r=>{reportAi.result=r;},v=>{reportAi.busy=v;},render);
 if($('#refresh-monitor'))$('#refresh-monitor').onclick=async()=>{await refreshMonitor(true);toast('Checks refreshed.');};
 if($('#sync-all'))$('#sync-all').onclick=()=>run(async()=>{const targets=state.accounts.accounts.filter(a=>a.id&&a.mode!=='import');if(!targets.length)return 'No accounts use a collector. Import accounts receive data by JSON import.';let ok=0,failed=0;for(const a of targets){const r=await api.syncAccount(a.id);r.status==='Failed'?failed++:ok++;}return `Synced ${ok} account${ok===1?'':'s'}${failed?`, ${failed} failed. Open the account to see why`:''}.`;});
 for(const k of ['search','account','status','provider','risk','kind'])if($('#'+k)&&$('#filtered-table'))$('#'+k)[k==='search'?'oninput':'onchange']=e=>{filters[k]=e.target.value;oppPage=1;filterTable();};
 if($('#log-more'))$('#log-more').onclick=()=>{showAllLog=true;render();};
 if($('#export-log'))$('#export-log').onclick=()=>download('stratus-audit-log.json',JSON.stringify(state.log,null,2),'application/json');
 if($('#import'))$('#import').onclick=()=>$('#import-file').click();
 if($('#template'))$('#template').onclick=()=>run(async()=>download('stratus-sample-inventory.json',JSON.stringify(await api.sample(),null,2),'application/json'));
 if($('#reset'))$('#reset').onclick=()=>{if(confirm('Replace ALL current inventory with the sample resources and reopen their decisions? Audit history and cloud accounts are kept.'))run(()=>api.seed(true),'Sample inventory restored.');};
 if($('#load-sample'))$('#load-sample').onclick=()=>run(()=>api.seed(false),'Sample inventory loaded.');
 if($('#org-form'))$('#org-form').onsubmit=e=>{e.preventDefault();run(()=>api.updateOrganization($('#org-name-input').value.trim()),'Organization name saved.');};
 if($('#member-form'))$('#member-form').onsubmit=e=>{e.preventDefault();run(()=>api.addMember({email:$('#member-email').value.trim(),name:$('#member-name').value.trim(),password:$('#member-password').value,role:$('#member-role').value}),'Member added.');};
 document.querySelectorAll('[data-remove-member]').forEach(b=>b.onclick=()=>{const m=state.org.members.find(x=>x.id===b.dataset.removeMember);if(m&&confirm(`Remove ${m.email}? They will be signed out and lose access.`))run(()=>api.removeMember(m.id),'Member removed.');});
 if($('#acct-size'))$('#acct-size').onchange=e=>{acctPager.size=+e.target.value;acctPager.page=1;render();};
 document.querySelectorAll('[data-acct-page]').forEach(b=>b.onclick=()=>{acctPager.page+=+b.dataset.acctPage;render();});
 document.querySelectorAll('[data-add-account]').forEach(b=>b.onclick=openAddAccount);
 document.querySelectorAll('[data-import-account]').forEach(b=>b.onclick=()=>{accountImportId=b.dataset.importAccount;$('#account-import-file').click();});
 document.querySelectorAll('[data-sync-account]').forEach(b=>b.onclick=()=>run(async()=>{const r=await api.syncAccount(b.dataset.syncAccount);return r.status==='Failed'?'Sync failed: '+r.message:`Synced ${r.resources} resource${r.resources===1?'':'s'}${r.removed?`, ${r.removed} removed`:''}.${r.message?' '+r.message:''}`;}));
 document.querySelectorAll('[data-test-account]').forEach(b=>b.onclick=()=>run(async()=>{const r=await api.testAccount(b.dataset.testAccount);return (r.ok?'Connected. ':'Connection failed. ')+r.message;}));
 document.querySelectorAll('[data-edit-account]').forEach(b=>b.onclick=()=>openEditAccount(b.dataset.editAccount));
 document.querySelectorAll('[data-remove-account]').forEach(b=>b.onclick=()=>{const a=state.accounts.accounts.find(x=>x.id===b.dataset.removeAccount);if(a&&confirm(`Remove "${a.name}"? Its ${a.resources} resource(s) and their recommendations will be deleted, and stored credentials erased. Audit history is kept.`))run(()=>api.deleteAccount(a.id),'Cloud account removed.');});
}
let accountImportId=null;

// ------------------------------------------------------------------- drawer
function showDrawer(html,label='Review'){lastFocus=document.activeElement;$('#drawer').innerHTML=`<div class="drawer-top"><span>${label}</span><button class="icon-button" id="close-drawer" aria-label="Close">×</button></div>${html}`;$('#overlay').hidden=false;$('#drawer').hidden=false;document.body.style.overflow='hidden';$('#close-drawer').onclick=closeDrawer;$('#close-drawer').focus();}
function closeDrawer(){$('#overlay').hidden=true;$('#drawer').hidden=true;document.body.style.overflow='';if(lastFocus?.isConnected)lastFocus.focus();}
function readCredentials(mode,required){
 const v=id=>($('#'+id)?.value||'').trim();
 const fields=mode==='aws'||mode==='aws_emu'?{access_key_id:v('cred-key'),secret_access_key:v('cred-secret'),regions:v('cred-regions')}:mode==='azure'||mode==='azure_emu'?{tenant_id:v('cred-tenant'),client_id:v('cred-client'),client_secret:v('cred-secret')}:null;
 if(!fields)return undefined;
 const filled=Object.values(fields).filter(Boolean).length;
 if(!required&&!filled)return undefined;
 if(filled<Object.keys(fields).length)throw Error('Fill in every credential field, or leave them all blank.');
 return fields;
}
function openAddAccount(){
 showDrawer(addAccountForm(),'New account');
 const form=$('#account-form');
 const refresh=()=>{const p=$('#acc-provider').value,m=$('#acc-mode').value;const [label,ph]=idLabel(p);$('#acc-ref-label').textContent=label;$('#acc-ref').placeholder=ph;$('#cred-slot').innerHTML=credentialFields(m);};
 $('#acc-provider').onchange=()=>{const p=$('#acc-provider').value;$('#acc-mode').innerHTML=MODES_BY_PROVIDER[p].map(([v,l])=>`<option value="${v}">${l}</option>`).join('');refresh();};
 $('#acc-mode').onchange=refresh;refresh();
 form.onsubmit=async e=>{e.preventDefault();const btn=form.querySelector('button[type=submit]');btn.disabled=true;$('#account-error').textContent='';
  try{
   const mode=$('#acc-mode').value,body={name:$('#acc-name').value.trim(),provider:$('#acc-provider').value,account_ref:$('#acc-ref').value.trim(),region:$('#acc-region').value.trim(),mode};
   const budget=$('#acc-budget').value;if(budget!=='')body.budget_usd=Number(budget);
   const creds=readCredentials(mode,true);if(creds)body.credentials=creds;
   const r=await api.addAccount(body);closeDrawer();await load();
   toast(['demo','aws_emu','azure_emu'].includes(mode)?`${mode==='demo'?'Demo':'Emulator'} account added with ${r.sync?.resources??0} VMs and 14 days of history.`:mode==='import'?'Cloud account added. Import its inventory to start optimizing.':'Account added. Press Test, then Sync now.');
   if(location.hash!=='#accounts')location.hash='accounts';
  }catch(err){if(err.status===401)return signOut(err.message);$('#account-error').textContent=err.message;btn.disabled=false;}};
 $('#acc-name').focus();
}
async function openEditAccount(id){
 const a=state.accounts.accounts.find(x=>x.id===id);if(!a)return;
 let runs=[];try{runs=a.mode==='import'?[]:(await api.accountSyncs(id)).runs;}catch(e){if(e.status===401)return signOut(e.message);}
 showDrawer(editAccountForm(a,runs),'Account settings');
 $('#edit-form').onsubmit=async e=>{e.preventDefault();const btn=$('#edit-form button[type=submit]');btn.disabled=true;$('#edit-error').textContent='';
  try{
   const budget=$('#edit-budget').value,body={name:$('#edit-name').value.trim(),budget_usd:budget===''?null:Number(budget)};
   const creds=readCredentials(a.mode,false);if(creds)body.credentials=creds;
   await api.editAccount(id,body);closeDrawer();await load();toast('Account updated.');
  }catch(err){if(err.status===401)return signOut(err.message);$('#edit-error').textContent=err.message;btn.disabled=false;}};
}
function historySection(points){
 if(points.length<2)return '<p>Not enough readings yet. History builds with every sync.</p>';
 const label=p=>new Date(p.time).toLocaleDateString([], {month:'short',day:'numeric'});
 return `<div class="chart-wrap tight">${lineChart(points.map(p=>({label:label(p),value:p.cpu})),{format:v=>Math.round(v)+'%',label:'CPU history',h:140})}</div><small>P95 CPU over ${points.length} readings, ${label(points[0])} to ${label(points.at(-1))}.</small>`;
}
function openDetail(id){const r=rows().find(r=>r.id===id);if(!r)return;showDrawer(`<h2>${esc(r.name)}</h2><p>${esc(r.provider)} · ${esc(accountName(r.accountId)||'No account')} · ${esc(r.env)} · ${esc(r.owner)}</p><div class="drawer-tags">${badge(r.kind)}${badge(r.status)}</div><div class="detail-savings"><span>Estimated monthly savings</span><strong>${money(r.saving)}</strong><span>${esc(r.action)}</span>${confidenceNote(r)}</div><h3>Why this was flagged</h3><p>${esc(r.reason)}</p><h3>Evidence</h3><div class="evidence-grid">${[['P95 CPU',r.cpu+'%'],['P95 memory',r.memory===null?'Unavailable':r.memory+'%'],['Network / day',r.network+' MB'],['Observation window',r.days+' days'],['Metric coverage',r.coverage+'%'],['Business critical',r.critical?'Yes':'No']].map(([k,v])=>`<div><small>${k}</small><strong>${v}</strong></div>`).join('')}</div><h3>History</h3><div id="history-slot"><p>Loading…</p></div><h3>Cost calculation</h3><p>${costExplanation(r)}</p><h3>Explanation</h3><p id="agent-explanation">${esc(r.reason)}</p><button class="text-button" id="explain" style="margin-top:4px">See more</button>${r.status==='Pending'&&r.saving>0?`<hr><label for="reviewer">Reviewer name</label><input id="reviewer" placeholder="Your name" maxlength="80" value="${esc(auth.email())}"><div class="actions"><button class="btn primary" id="approve">Approve plan</button><button class="btn" id="dismiss">Dismiss</button></div>`:''}${r.status==='Pending'&&!r.saving?'<div class="actions"><button class="btn" id="dismiss">Acknowledge and dismiss</button></div>':''}${r.status==='Approved'?'<div class="actions"><button class="btn primary" id="implement">Mark implemented</button><button class="btn" id="simulate">Simulate execution</button><button class="btn" id="reopen">Reopen review</button></div><p class="hint">Make the change in your cloud, then press Mark implemented. The next sync verifies the saving.</p>':''}${r.status==='Simulated'?'<div class="actions"><button class="btn primary" id="implement">Mark implemented</button><button class="btn" id="reopen">Reopen review</button></div>':''}${r.status==='Dismissed'?'<div class="actions"><button class="btn" id="reopen">Reopen review</button></div>':''}${aiSection(r)}<p class="resource-id">Resource ID: ${esc(r.id)}</p>`);
 api.history(id).then(d=>{const slot=$('#history-slot');if(slot&&!$('#drawer').hidden)slot.innerHTML=historySection(d.points);}).catch(()=>{const slot=$('#history-slot');if(slot)slot.innerHTML='<p>History is unavailable.</p>';});
 if($('#explain'))$('#explain').onclick=async()=>{const button=$('#explain');button.disabled=true;try{const result=await api.explain(id);$('#agent-explanation').textContent=result.text;button.textContent='Source: '+result.source;}catch(error){toast(error.message);}finally{if(button.isConnected)button.disabled=false;}};
 const slot=()=>$('#ai-slot'),aiRun=(btn,fn,html)=>{const b=$(btn);if(!b)return;b.onclick=async()=>{b.disabled=true;slot().innerHTML='<p>Working…</p>';try{slot().innerHTML=html(await fn(id));}catch(e){if(e.status===401)return signOut(e.message);slot().innerHTML=aiError(e.message);}finally{if(b.isConnected)b.disabled=false;}};};
 aiRun('#ai-assist',api.aiApproval,aiAssistHtml);
 if($('#approve'))$('#approve').onclick=()=>{const name=$('#reviewer').value.trim();if(!name){$('#reviewer').focus();toast('Enter a reviewer name for the audit record.');return;}changeStatus(id,'Approved','Plan approved',name);};
 if($('#dismiss'))$('#dismiss').onclick=()=>changeStatus(id,'Dismissed','Recommendation dismissed');
 if($('#reopen'))$('#reopen').onclick=()=>changeStatus(id,'Pending','Recommendation reopened');
 if($('#simulate'))$('#simulate').onclick=()=>changeStatus(id,'Simulated','Execution simulated');
 if($('#implement'))$('#implement').onclick=()=>changeStatus(id,'Implemented','Marked implemented. The next sync verifies the saving.');
}
function aiSection(r){
 if(!state.org?.llmConfigured||!((r.status==='Pending'&&r.saving>0)||r.status==='Approved'))return '';
 return `<hr><h3>AI assistance</h3><p class="hint">Drafts only. The rules still decide savings, risk and status.</p><div class="actions"><button class="btn" id="ai-assist">Review with AI</button></div><div id="ai-slot" aria-live="polite"></div>`;
}
function costExplanation(r){if(r.kind==='Idle resource')return `${money(r.cost)} monthly compute × 100% stopped time = ${money(r.saving)}. Storage and other charges continue.`;if(r.kind==='Oversized resource')return `${money(r.cost)} current − ${money(r.targetCost)} smaller configuration = ${money(r.saving)}. Validate SKU compatibility and current pricing.`;if(r.kind==='After-hours usage')return `${money(r.cost)} × (1 − 220 proposed hours ÷ ${r.hours} current hours) ≈ ${money(r.saving)}. The schedule is proposed, not observed.`;return 'No savings estimate is issued for this finding.';}
function changeStatus(id,status,title,reviewer=''){
 const r=rows().find(r=>r.id===id);
 const action={Approved:'approve',Dismissed:'dismiss',Pending:'reopen',Simulated:'simulate',Implemented:'implement'}[status];
 run(async()=>{await api.decision(id,action,r.version,r.generation,status==='Approved'?reviewer:'');closeDrawer();},status==='Simulated'?'Dry run recorded. No cloud resources changed.':title.endsWith('.')?title:title+'.');
}
function guide(){return `<div class="panel guide"><h2>How data flows</h2><div class="pipeline"><div><b>1 · Collect</b><span>Live AWS/Azure sync, demo or JSON import</span></div><div><b>2 · Analyze</b><span>Rules, history and confidence</span></div><div><b>3 · Decide</b><span>Version-checked approvals</span></div><div><b>4 · Verify</b><span>Ledger checks the saving later</span></div></div><h3>Inventory fields</h3><p>id, name, provider (AWS, Azure or GCP), accountId (a cloud account ID from Cloud accounts), region, type, env (Development, Staging, Production), owner, cost and targetCost (USD per month), cpu and memory (P95 %), network (MB/day), days, coverage (%), hours (monthly run hours), critical (boolean). Memory may be null. Up to 500 records. The provider must match the account's cloud.</p><h3>Read-only access per cloud</h3><ul><li>AWS: <code>ec2:DescribeInstances</code>, <code>cloudwatch:GetMetricData</code>, <code>sts:GetCallerIdentity</code>. Memory needs the CloudWatch agent.</li><li>Azure: Reader and Monitoring Reader on the subscription. Memory needs the Azure Monitor Agent.</li><li>GCP: JSON import only for now. Memory needs the Ops Agent.</li></ul><h3>Rules</h3><ul><li>Needs 14 days of data, 95% coverage and memory metrics.</li><li>Idle: non-production, non-critical, CPU under 5%, memory under 15%, network under 1 MB/day.</li><li>Oversized: CPU under 30%, memory under 40%, and a cheaper size exists.</li><li>After-hours: non-critical development VM running over 300 hours a month.</li><li>One finding per resource, so savings never overlap. Untagged cloud resources count as Production, so they are never suggested for stopping.</li></ul></div>`;}
function download(name,data,type){const url=URL.createObjectURL(new Blob([data],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function exportReport(){try{const blob=await api.report();download('cloud-cost-recommendations.csv',blob,'text/csv');toast('Report exported.');}catch(error){toast(error.message);}}
async function readJson(file){if(file.size>1000000)throw Error('File is too large. Maximum size is 1 MB.');return validateImport(JSON.parse(await file.text()));}
$('#import-file').onchange=async e=>{const f=e.target.files[0];if(!f)return;try{const inventory=await readJson(f);if(!confirm(`Replace ALL inventory with ${inventory.length} resources? Changed-resource approvals will be invalidated; audit history is retained.`))return;await run(()=>api.inventory(inventory,true),'Inventory imported and analyzed.');}catch(error){toast('Import failed: '+error.message);}finally{e.target.value='';}};
$('#account-import-file').onchange=async e=>{const f=e.target.files[0],id=accountImportId;if(!f||!id)return;const a=state.accounts.accounts.find(x=>x.id===id);try{const inventory=(await readJson(f)).map(r=>({...r,accountId:r.accountId||id}));await run(()=>api.inventory(inventory,false),`${inventory.length} resources imported into ${a?.name||'account'}.`);}catch(error){toast('Import failed: '+error.message);}finally{e.target.value='';}};
$('#overlay').onclick=closeDrawer;
document.addEventListener('click',e=>{const b=e.target.closest?.('[data-copy]');if(!b)return;navigator.clipboard?.writeText(b.dataset.copy).then(()=>toast('Copied.'),()=>toast('Copy failed. Select the text and copy it manually.'));});
$('#menu-toggle').onclick=()=>{const open=document.body.classList.toggle('nav-open');$('#menu-toggle').setAttribute('aria-expanded',String(open));};
document.addEventListener('keydown',e=>{if($('#drawer').hidden)return;if(e.key==='Escape')closeDrawer();if(e.key==='Tab'){const f=[...$('#drawer').querySelectorAll('button,input,a,select')].filter(x=>!x.disabled);if(e.shiftKey&&document.activeElement===f[0]){e.preventDefault();f.at(-1).focus();}else if(!e.shiftKey&&document.activeElement===f.at(-1)){e.preventDefault();f[0].focus();}}});
$('#view').addEventListener('toggle',e=>{const id=e.target.dataset?.issue;if(id)e.target.open?monitorUi.opened.add(id):monitorUi.opened.delete(id);},true);
window.addEventListener('hashchange',()=>{closeDrawer();if(location.hash.startsWith('#monitor')||location.hash==='#report')state.monitor=null;if(authenticated)render();window.scrollTo(0,0);});
$('#logout').onclick=async()=>{await api.logout().catch(()=>{});signOut();};
function showLoadError(error){
 document.body.classList.remove('signed-out');setHeading('Workspace unavailable','');$('#heading-actions').innerHTML='';$('#navigation').innerHTML='';
 $('#view').innerHTML=`<div class="panel empty"><h3>Could not load your workspace</h3><p>${esc(error.message)}</p><div class="actions" style="justify-content:center"><button class="btn primary" id="retry-load">Try again</button><button class="btn" id="retry-signout">Sign out</button></div></div>`;
 $('#retry-load').onclick=()=>load().catch(e=>e.status===401?signOut(e.message):showLoadError(e));
 $('#retry-signout').onclick=()=>signOut();
}
if(auth.get())load().catch(error=>error.status===401?signOut(error.message):showLoadError(error));else showLogin();
