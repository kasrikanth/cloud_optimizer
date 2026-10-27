import {money} from './utils.js';
export {money};
export const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths={overview:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',opportunities:'m12 3-8 11h7l-1 7 10-12h-8z',approvals:'M9 4H5v17h14V4h-4 M9 3h6v4H9z m-1 11 3 3 5-6',activity:'M3 12h4l3-8 4 16 3-8h4',integrations:'M9 3v5 M15 3v5 M6 8h12v3a6 6 0 0 1-12 0z M12 17v4',scan:'M20 7V3l-3 3a8 8 0 1 0 3 9 M20 3h-5',download:'M12 3v12 m-5-5 5 5 5-5 M4 16v5h16v-5',accounts:'M7 18a5 5 0 1 1 1-10 6 6 0 0 1 11 2 4 4 0 0 1-1 8z',compare:'M7 4v16 M17 4v16 M3 8l4-4 4 4 M13 16l4 4 4-4',monitor:'M3 12h4l2-6 4 12 2-6h6',plus:'M12 5v14 M5 12h14',savings:'M12 2v20 M17 6H9a3 3 0 0 0 0 6h6a3 3 0 0 1 0 6H6',organization:'M3 21h18 M5 21V7l7-4 7 4v14 M9 21v-6h6v6',report:'M6 3h9l4 4v14H6z M14 3v5h5 M9 13h6 M9 17h6'};
export const icon=n=>`<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[n]||paths.accounts}"/></svg>`;
export const badge=(text,cls)=>`<span class="badge ${esc(cls??String(text).toLowerCase().split(' ')[0])}">${esc(text)}</span>`;
export const providerMark=p=>`<span class="cloud-icon ${esc(String(p||'').toLowerCase())}">${p==='Azure'?'Az':p==='AWS'?'AWS':p==='GCP'?'GCP':'?'}</span>`;
export const metric=(label,value,note,green=false)=>`<div class="metric ${green?'savings':''}"><div class="metric-label">${label}</div><div class="metric-value">${value}</div><div class="metric-note">${note}</div></div>`;
export const sum=(rs,key)=>rs.reduce((n,r)=>n+r[key],0);
export function ago(iso){if(!iso)return 'Never';const s=Math.max(0,(Date.now()-new Date(iso).getTime())/1000);if(s<60)return 'Just now';if(s<3600)return Math.floor(s/60)+' min ago';if(s<86400)return Math.floor(s/3600)+' h ago';return Math.floor(s/86400)+' d ago';}

// Small dependency-free SVG charts. Values are plain numbers; labels are escaped.
export function lineChart(points,{w=620,h=170,format=v=>String(v),label='Trend'}={}){
  if(points.length<2)return '';
  const pad={l:56,r:12,t:12,b:26},vals=points.map(p=>p.value);
  let lo=Math.min(...vals),hi=Math.max(...vals);if(lo===hi){lo-=1;hi+=1;}const span=hi-lo;lo-=span*.1;hi+=span*.1;
  const x=i=>pad.l+i/(points.length-1)*(w-pad.l-pad.r),y=v=>pad.t+(1-(v-lo)/(hi-lo))*(h-pad.t-pad.b);
  const line=points.map((p,i)=>`${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ');
  const ticks=[hi,(hi+lo)/2,lo].map(v=>`<line x1="${pad.l}" x2="${w-pad.r}" y1="${y(v)}" y2="${y(v)}" class="grid"/><text x="${pad.l-8}" y="${y(v)+4}" text-anchor="end">${esc(format(v))}</text>`).join('');
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(label)}: from ${esc(format(vals[0]))} to ${esc(format(vals.at(-1)))}">${ticks}<polygon points="${pad.l},${h-pad.b} ${line} ${w-pad.r},${h-pad.b}" class="area"/><polyline points="${line}" class="line"/><circle cx="${x(points.length-1)}" cy="${y(vals.at(-1))}" r="3.5" class="dot"/><text x="${pad.l}" y="${h-6}">${esc(points[0].label)}</text><text x="${w-pad.r}" y="${h-6}" text-anchor="end">${esc(points.at(-1).label)}</text></svg>`;
}
