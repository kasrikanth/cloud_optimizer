const base=(import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/,'');
const store=(key)=>({get:()=>sessionStorage.getItem(key)||'',set:v=>sessionStorage.setItem(key,v),clear:()=>sessionStorage.removeItem(key)});
const tokenStore=store('optimizer-api-token'),emailStore=store('optimizer-user-email');
export const auth={
  get:tokenStore.get,
  set:(token,email='')=>{tokenStore.set(token);if(email)emailStore.set(email);},
  email:emailStore.get,
  clear:()=>{tokenStore.clear();emailStore.clear();}
};
export class ApiError extends Error{constructor(message,status){super(message);this.status=status;}}
export async function request(path,{method='GET',body,raw=false}={}){
  let response;
  const token=auth.get();
  try{response=await fetch(base+path,{method,headers:{...(token?{Authorization:'Bearer '+token}:{}),...(body!==undefined?{'Content-Type':'application/json'}:{})},body:body!==undefined?JSON.stringify(body):undefined});}
  catch{throw new ApiError('Cannot reach the backend. Start FastAPI on port 8000 and check the frontend proxy.',0);}
  if(!response.ok){let data;try{data=await response.json();}catch{}const detail=data?.detail;throw new ApiError(typeof detail==='string'?detail:detail?detail.map(d=>d.loc.join('.')+': '+d.msg).join('; '):'Request failed ('+response.status+')',response.status);}
  return raw?response.blob():response.json();
}
export const api={
  signup:body=>request('/api/auth/signup',{method:'POST',body}),
  login:(email,password)=>request('/api/auth/login',{method:'POST',body:{email,password}}),
  logout:()=>request('/api/auth/logout',{method:'POST'}),
  workspace:()=>request('/api/workspace'),
  dashboard:()=>request('/api/dashboard'),
  accounts:()=>request('/api/accounts'),
  addAccount:body=>request('/api/accounts',{method:'POST',body}),
  deleteAccount:id=>request('/api/accounts/'+encodeURIComponent(id),{method:'DELETE'}),
  editAccount:(id,body)=>request('/api/accounts/'+encodeURIComponent(id),{method:'PATCH',body}),
  testAccount:id=>request('/api/accounts/'+encodeURIComponent(id)+'/test',{method:'POST'}),
  syncAccount:id=>request('/api/accounts/'+encodeURIComponent(id)+'/sync',{method:'POST'}),
  accountSyncs:id=>request('/api/accounts/'+encodeURIComponent(id)+'/syncs'),
  history:id=>request('/api/resources/'+encodeURIComponent(id)+'/history'),
  organization:()=>request('/api/organization'),
  updateOrganization:name=>request('/api/organization',{method:'PUT',body:{name}}),
  ask:question=>request('/api/ask',{method:'POST',body:{question}}),
  comparison:()=>request('/api/comparison'),
  cloudServices:()=>request('/api/cloud-services'),
  monitor:()=>request('/api/monitor'),
  scan:()=>request('/api/scans',{method:'POST'}),
  seed:replace=>request('/api/seed',{method:'POST',body:{replace}}),
  inventory:(resources,replace=true)=>request('/api/inventory',{method:'POST',body:{resources,replace}}),
  decision:(id,action,expected_version,expected_generation,reviewer='')=>request('/api/recommendations/'+encodeURIComponent(id)+'/decision',{method:'POST',body:{action,expected_version,expected_generation,reviewer}}),
  sample:()=>request('/api/sample-inventory'),
  report:()=>request('/api/reports/recommendations.csv',{raw:true}),
  explain:id=>request('/api/explanations/'+encodeURIComponent(id),{method:'POST'}),
  addMember:body=>request('/api/members',{method:'POST',body}),
  removeMember:id=>request('/api/members/'+encodeURIComponent(id),{method:'DELETE'}),
  aiMonitor:()=>request('/api/ai/monitor-diagnosis',{method:'POST'}),
  aiReport:()=>request('/api/ai/report-narrative',{method:'POST'}),
  aiApproval:id=>request('/api/ai/approval-assist/'+encodeURIComponent(id),{method:'POST'}),
  aiAnomaly:id=>request('/api/ai/anomaly/'+encodeURIComponent(id),{method:'POST'}),
  forecast:()=>request('/api/forecast'),
  aiForecast:()=>request('/api/ai/forecast',{method:'POST'})
};
