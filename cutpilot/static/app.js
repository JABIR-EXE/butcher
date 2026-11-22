function setTheme(theme, persist=true){
  const next = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = next;
  document.documentElement.style.colorScheme = next;
  const meta = document.querySelector('#theme-color-meta');
  if(meta) meta.setAttribute('content', next === 'dark' ? '#0d1727' : '#f4f7f8');
  const button = document.querySelector('#theme-toggle');
  if(button){
    const action = next === 'dark' ? 'light' : 'dark';
    button.setAttribute('aria-label', `Switch to ${action} mode`);
    button.setAttribute('title', `Switch to ${action} mode`);
    const label = button.querySelector('.theme-toggle-text');
    if(label) label.textContent = `${action[0].toUpperCase()}${action.slice(1)} mode`;
    button.setAttribute('aria-pressed', String(next === 'dark'));
  }
  if(persist){ try{ localStorage.setItem('cutpilot-theme', next); }catch(_){} }
  if(typeof state !== 'undefined' && state.page === 'dashboard') requestAnimationFrame(()=>drawLineChart($('#revenue-chart'),state.analytics?.daily||[],'revenue'));
  if(typeof state !== 'undefined' && state.page === 'analytics') requestAnimationFrame(()=>drawLineChart($('#analytics-chart'),state.analytics?.daily||[],'revenue'));
}

const state = {
  page: 'dashboard', summary: null, products: [], suppliers: [], analytics: null,
  recommendations: [], orders: [], waste: [], movements: [], imports: [], settings: {},
  importPreview: null, productImportPreview: null, salesFileData: null, productFileData: null, selectedRecommendations: new Set(), selectionInitialized: false, chatBusy: false
};

const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
const money = (value) => {
  const currency = state.settings.currency || state.summary?.currency || 'USD';
  try { return new Intl.NumberFormat(undefined, {style:'currency',currency,maximumFractionDigits:2}).format(Number(value)||0); }
  catch { return `${currency} ${(Number(value)||0).toFixed(2)}`; }
};
const num = (value, digits=1) => Number(value||0).toLocaleString(undefined,{maximumFractionDigits:digits});
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dateShort = (value) => { if(!value) return '—'; const d = new Date(value); return Number.isNaN(d.getTime()) ? esc(value) : d.toLocaleDateString(undefined,{month:'short',day:'numeric'}); };
const dateTime = (value) => { if(!value) return '—'; const d = new Date(value); return Number.isNaN(d.getTime()) ? esc(value) : d.toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}); };
const statusClass = (status) => `status status-${String(status||'').toLowerCase().replace(/[^a-z_]/g,'')}`;

async function api(path, options={}) {
  const config = { ...options, headers: { ...(options.body ? {'Content-Type':'application/json'} : {}), ...(options.headers||{}) } };
  if (config.body && typeof config.body !== 'string') config.body = JSON.stringify(config.body);
  const response = await fetch(path, config);
  const type = response.headers.get('content-type') || '';
  if (response.status === 401 && path !== '/api/auth/me') { window.location.href = '/login?reason=expired'; throw new Error('Your session has expired. Please sign in again.'); }
  if (!response.ok) {
    const error = type.includes('application/json') ? await response.json() : {error: await response.text()};
    throw new Error(error.error || `Request failed (${response.status})`);
  }
  return type.includes('application/json') ? response.json() : response.text();
}
function toast(message, type='success') {
  const item = document.createElement('div'); item.className = `toast ${type==='error'?'error':''}`; item.textContent = message;
  $('#toast-region').append(item); setTimeout(()=>item.remove(), 4200);
}
function showModal(title, body, eyebrow='WORKSPACE') {
  $('#modal-title').textContent=title; $('#modal-eyebrow').textContent=eyebrow; $('#modal-body').innerHTML=body; $('#modal-backdrop').classList.remove('hidden');
}
function closeModal(){ $('#modal-backdrop').classList.add('hidden'); $('#modal-body').innerHTML=''; }
function go(page){
  if(!$('#page-'+page)) return;
  state.page=page;
  $$('.page').forEach(el=>el.classList.toggle('active',el.id===`page-${page}`));
  $$('.nav-item[data-page]').forEach(el=>el.classList.toggle('active',el.dataset.page===page));
  const label = ({dashboard:'Overview',inventory:'Products & stock',imports:'Import data',analytics:'Sales & profit',purchasing:'Buying suggestions',orders:'Purchase orders',suppliers:'Suppliers',waste:'Waste & expiry',assistant:'Ask CutPilot',guide:'Help & setup guide',settings:'Settings',pricing:'Plans & pricing'})[page]||page;
  $('#page-crumb').textContent=label;
  $('#sidebar').classList.remove('open');
  if(page==='inventory') loadInventory();
  if(page==='purchasing') loadPurchasing();
  if(page==='orders') loadOrders();
  if(page==='suppliers') loadSuppliers();
  if(page==='analytics') loadAnalytics();
  if(page==='waste') loadWaste();
  if(page==='imports') loadImports();
  if(page==='settings') loadSettings();
}
async function refreshAll(){
  const [summary,products,suppliers,analytics,recommendations,orders,waste,movements,imports,settings] = await Promise.all([
    api('/api/summary'),api('/api/products'),api('/api/suppliers'),api('/api/analytics'),api('/api/recommendations'),api('/api/purchase-orders'),api('/api/waste'),api('/api/movements'),api('/api/imports'),api('/api/settings')
  ]);
  Object.assign(state,{summary,products,suppliers,analytics,recommendations,orders,waste,movements,imports,settings});
  renderDashboard(); renderInventory(); renderAnalytics(); renderPurchasing(); renderOrders(); renderSuppliers(); renderWaste(); renderImportHistory(); renderSettings();
}
function statusFor(p){ if(Number(p.on_hand)<=0.000001) return 'out'; if(Number(p.on_hand)<=Number(p.min_stock)) return 'low'; return 'healthy'; }
function statusLabel(status){ return ({out:'Out of stock',low:'Low stock',healthy:'Healthy',draft:'Draft',approved:'Approved',sent:'Sent',partially_received:'Partial',received:'Received',cancelled:'Cancelled'})[status]||status; }
function productCell(p){ return `<div class="product-cell"><div class="product-thumb">${iconForCategory(p.category)}</div><div><div class="product-name">${esc(p.name)}</div><div class="product-meta">${esc(p.category||'Uncategorized')}</div></div></div>`; }
function iconForCategory(cat=''){
  const c=String(cat).toLowerCase();
  const svg=(shape,fill1,fill2,detail)=>`<svg viewBox="0 0 48 48" aria-hidden="true" focusable="false"><defs><linearGradient id="${shape}-g" x1="7" y1="5" x2="42" y2="44" gradientUnits="userSpaceOnUse"><stop stop-color="${fill1}"/><stop offset="1" stop-color="${fill2}"/></linearGradient><linearGradient id="${shape}-shine" x1="12" y1="8" x2="31" y2="27" gradientUnits="userSpaceOnUse"><stop stop-color="#fff" stop-opacity=".78"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>${detail.replaceAll('FILL',`url(#${shape}-g)`).replaceAll('SHINE',`url(#${shape}-shine)`)}</svg>`;
  if(c.includes('poultry')||c.includes('chicken')||c.includes('turkey')) return svg('poultry','#ffd18e','#d7863e',`<path d="M12 28c-3-6 1-13 8-14 5-1 9 1 12 5l5 5c3 3 3 8 0 11-3 3-7 3-10 0l-4-4c-4 2-9 1-11-3Z" fill="FILL" stroke="#a95d2e" stroke-width="1.8"/><path d="M13 22c2-5 7-7 12-5" fill="none" stroke="SHINE" stroke-width="3" stroke-linecap="round"/><circle cx="37" cy="36" r="3.4" fill="#f4e7d2" stroke="#c69d71" stroke-width="1.5"/>`);
  if(c.includes('lamb')||c.includes('mutton')||c.includes('sheep')) return svg('lamb','#f5a5a0','#b94d5b',`<path d="M10 28c0-7 6-12 13-11 3-7 13-6 15 1 5 1 7 8 3 12-1 6-8 9-13 6-6 5-17 1-18-8Z" fill="FILL" stroke="#97404d" stroke-width="1.8"/><path d="M17 23c4-5 11-6 16-2" fill="none" stroke="SHINE" stroke-width="3" stroke-linecap="round"/><circle cx="25" cy="29" r="4" fill="#f8d2bf" stroke="#e98f89" stroke-width="1.5"/>`);
  if(c.includes('beef')||c.includes('cow')||c.includes('veal')) return svg('beef','#f58b88','#a9364e',`<path d="M7 25c1-8 10-15 20-14 10 0 16 7 14 16-2 9-12 15-21 14C11 40 6 33 7 25Z" fill="FILL" stroke="#943247" stroke-width="2"/><path d="M14 21c5-6 14-8 22-3" fill="none" stroke="SHINE" stroke-width="3.5" stroke-linecap="round"/><path d="M16 29c5-3 10-3 15 1m-12 5c4-2 7-2 10 0" fill="none" stroke="#ffe0d4" stroke-width="2.8" stroke-linecap="round"/><ellipse cx="29" cy="26" rx="4" ry="3" fill="#f8d4bf" stroke="#e9a08e" stroke-width="1.4"/>`);
  if(c.includes('pork')) return svg('pork','#ffc0b7','#d96e79',`<path d="M8 23c3-8 12-13 22-10 8 2 12 9 10 17-2 8-12 12-21 10C9 38 5 31 8 23Z" fill="FILL" stroke="#a84f5a" stroke-width="1.8"/><path d="M15 20c5-5 13-6 20-2" fill="none" stroke="SHINE" stroke-width="3" stroke-linecap="round"/><circle cx="25" cy="28" r="7" fill="#f4e4d4" stroke="#cf8990" stroke-width="1.8"/><circle cx="25" cy="28" r="3" fill="#d66a79"/>`);
  if(c.includes('fish')||c.includes('seafood')) return svg('fish','#9ed8ee','#397eae',`<path d="M8 24c7-10 21-12 29 0-8 12-22 10-29 0Z" fill="FILL" stroke="#2f698e" stroke-width="1.8"/><path d="m35 24 7-7v14l-7-7Z" fill="#6db6da" stroke="#2f698e" stroke-width="1.5"/><circle cx="17" cy="22" r="1.8" fill="#173d59"/><path d="M14 29c5 3 12 3 17 0" fill="none" stroke="SHINE" stroke-width="2.5" stroke-linecap="round"/>`);
  if(c.includes('sausage')||c.includes('processed')) return svg('sausage','#f1ae86','#b95a48',`<g transform="rotate(-27 24 24)"><rect x="9" y="16" width="30" height="16" rx="8" fill="FILL" stroke="#94483d" stroke-width="1.8"/><path d="M12 20c5-4 14-5 21-1" fill="none" stroke="SHINE" stroke-width="3" stroke-linecap="round"/><path d="M10 22 6 20m32 8 4 2" stroke="#94483d" stroke-width="2" stroke-linecap="round"/></g>`);
  return svg('meat','#f48e88','#b83e50',`<path d="M7 25c1-8 10-15 20-14 10 0 16 7 14 16-2 9-12 15-21 14C11 40 6 33 7 25Z" fill="FILL" stroke="#943247" stroke-width="2"/><path d="M14 21c5-6 14-8 22-3" fill="none" stroke="SHINE" stroke-width="3.5" stroke-linecap="round"/><path d="M16 29c5-3 10-3 15 1" fill="none" stroke="#ffe0d4" stroke-width="2.8" stroke-linecap="round"/>`);
}
function miniIcon(token){
  const paths={
    '↗':'<path d="M5 17 17 5M8 5h9v9"/>',
    '◆':'<path d="m12 3 9 9-9 9-9-9 9-9Z"/>',
    '!':'<path d="M12 3 21 20H3L12 3Z"/><path d="M12 9v5m0 3h.01"/>',
    '✳':'<path d="M12 3v4m0 10v4M3 12h4m10 0h4M5.6 5.6l2.8 2.8m7.2 7.2 2.8 2.8m0-12.8-2.8 2.8m-7.2 7.2-2.8 2.8"/><circle cx="12" cy="12" r="3.5"/>',
    '◫':'<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 4v16m6-16v16"/>',
    '⌁':'<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    '◌':'<circle cx="12" cy="12" r="8"/><path d="M8 8l8 8"/>',
    '×':'<path d="m6 6 12 12M18 6 6 18"/>',
    '▤':'<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v5h4M9 13h7m-7 4h7"/>',
    '◷':'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    '↘':'<path d="M5 7 17 19M8 19h9v-9"/>',
    '✓':'<path d="m5 12 4.5 4.5L19 7"/>',
    '✎':'<path d="m4 16.5-.8 4.3 4.3-.8L20 7.5 16.5 4 4 16.5Z"/><path d="m14.8 5.7 3.5 3.5"/>',
    '➤':'<path d="m4 12 16-8-5 16-3-6-8-2Z"/><path d="m12 14 8-10"/>'
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths[token]||paths['◆']}</svg>`;
}
function metric(label,value,foot,icon,kind='mint'){return `<div class="metric-card"><div class="metric-label">${esc(label)}<span class="metric-icon ${kind}">${miniIcon(icon)}</span></div><div class="metric-value">${value}</div><div class="metric-foot">${foot}</div></div>`;}

function renderDashboard(){
  const s=state.summary;if(!s)return;
  $('#sidebar-business').textContent=s.business_name||'My Butcher Shop';
  $('#nav-stock-count').textContent=s.low_stock_count+s.out_of_stock_count;
  $('#today-chip').textContent=new Date(`${s.today}T12:00:00`).toLocaleDateString(undefined,{weekday:'short',month:'short',day:'numeric',year:'numeric'});
  const a=s.analytics||{};
  const change=a.revenue_change_pct;
  $('#dashboard-metrics').innerHTML=[
    metric('7-DAY REVENUE',money(a.revenue_7d),change===null?'No prior-week comparison':`${change>=0?'↑':'↓'} ${Math.abs(change).toFixed(1)}% vs previous week`,'↗','mint'),
    metric('EST. GROSS PROFIT · 7 DAYS',money(a.estimated_gross_profit_7d||0),'Revenue less recorded product cost · estimate','◆','blue'),
    metric('LOW / OUT OF STOCK',`${s.low_stock_count+s.out_of_stock_count}`,`${s.out_of_stock_count} out · ${s.low_stock_count} low`,'!','amber'),
    metric('AI ORDER SUGGESTIONS',`${s.suggested_order_count}`,`${money(s.suggested_order_value)} estimated value`,'✳','violet')
  ].join('');
  $('#revenue-change').textContent=change===null?'Import more sales history':`${change>=0?'+':''}${change}% week over week`;
  drawLineChart($('#revenue-chart'),a.daily||[], 'revenue');
  const insightItems=[];
  if(s.out_of_stock_count) insightItems.push({icon:'!',kind:'warn',title:`${s.out_of_stock_count} product${s.out_of_stock_count===1?' is':'s are'} out of stock`,body:'Review availability and update stock records.'});
  if(s.low_stock_count) insightItems.push({icon:'↘',kind:'warn',title:`${s.low_stock_count} product${s.low_stock_count===1?' is':'s are'} below minimum`,body:'Check reorder suggestions before your next delivery.'});
  if(s.suggested_order_count) insightItems.push({icon:'✳',kind:'good',title:`${s.suggested_order_count} purchase suggestions ready`,body:`Estimated buying value: ${money(s.suggested_order_value)}.`});
  if(s.expiring_batches?.length) insightItems.push({icon:'◷',kind:'warn',title:`${s.expiring_batches.length} batch(es) nearing expiry`,body:'Review batch dates and plan to use stock first.'});
  if(!insightItems.length) insightItems.push({icon:'✓',kind:'good',title:'Your workspace is looking steady',body:'Import sales data regularly to keep demand analysis current.'});
  $('#insights-list').innerHTML=insightItems.slice(0,4).map(x=>`<div class="insight-item"><div class="insight-icon ${x.kind}">${miniIcon(x.icon)}</div><div><b>${esc(x.title)}</b><p>${esc(x.body)}</p></div></div>`).join('');
  const watch=[...(s.out_of_stock||[]).map(p=>({...p,_status:'out'})),...(s.low_stock||[]).map(p=>({...p,_status:'low'}))].slice(0,6);
  $('#low-stock-table').innerHTML=watch.length?`<table class="data-table"><thead><tr><th>PRODUCT</th><th>ON HAND</th><th>MINIMUM</th><th>STATUS</th></tr></thead><tbody>${watch.map(p=>`<tr><td>${productCell(p)}</td><td><b>${num(p.on_hand,2)} ${esc(p.stock_unit)}</b></td><td>${num(p.min_stock,2)} ${esc(p.stock_unit)}</td><td><span class="${statusClass(p._status)}">${statusLabel(p._status)}</span></td></tr>`).join('')}</tbody></table>`:`<div class="empty-state compact">No low-stock products right now.</div>`;
  $('#activity-list').innerHTML=s.recent_activity?.length?s.recent_activity.map(x=>`<div class="activity-row"><span class="activity-dot"></span><div><strong>${esc(x.description)}</strong><small>${dateTime(x.created_at)}</small></div></div>`).join(''):`<div class="empty-state compact">No activity yet. Add a product or import sales to get started.</div>`;
  $('#demo-callout').classList.toggle('hidden',s.product_count>0);
  $('#dashboard-banner').classList.toggle('hidden',!(s.out_of_stock_count||s.low_stock_count));
  $('#banner-title').textContent=s.out_of_stock_count?`${s.out_of_stock_count} product(s) currently out of stock`:'Some products are below minimum stock';
  $('#banner-copy').textContent='Review stock levels and purchasing suggestions before confirming your next supplier order.';
}
function drawLineChart(canvas, rows, key){
  if(!canvas)return;const rect=canvas.getBoundingClientRect();const dpr=window.devicePixelRatio||1;const w=Math.max(300,rect.width),h=Math.max(170,rect.height||220);canvas.width=w*dpr;canvas.height=h*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);
  const values=rows.map(r=>Number(r[key]||0));if(!values.length||values.every(v=>v===0)){ctx.fillStyle='#a4afbd';ctx.font='11px DM Sans';ctx.textAlign='center';ctx.fillText('Import sales data to see your trend',w/2,h/2);return;}
  const left=38,right=12,top=15,bottom=26,chartW=w-left-right,chartH=h-top-bottom,max=Math.max(...values)*1.18||1;ctx.font='9px DM Sans';ctx.textAlign='right';
  const css=getComputedStyle(document.documentElement);const gridColor=css.getPropertyValue('--chart-grid').trim()||'#dfe2ec';const labelColor=css.getPropertyValue('--chart-label').trim()||'#8791a7';const accentColor=css.getPropertyValue('--chart-color').trim()||'#8069ea';const accentRgb=css.getPropertyValue('--chart-rgb').trim()||'128,105,234';
  for(let i=0;i<4;i++){const y=top+(chartH/3)*i;ctx.strokeStyle=gridColor;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w-right,y);ctx.stroke();ctx.fillStyle=labelColor;ctx.fillText((max*(1-i/3)).toFixed(0),left-8,y+3);}
  const points=values.map((v,i)=>({x:left+(values.length===1?chartW/2:i*chartW/(values.length-1)),y:top+chartH-(v/max)*chartH}));
  const gradient=ctx.createLinearGradient(0,top,0,top+chartH);gradient.addColorStop(0,`rgba(${accentRgb},.28)`);gradient.addColorStop(1,`rgba(${accentRgb},0)`);ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.lineTo(points.at(-1).x,top+chartH);ctx.lineTo(points[0].x,top+chartH);ctx.closePath();ctx.fillStyle=gradient;ctx.fill();
  ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.strokeStyle=accentColor;ctx.lineWidth=2.5;ctx.lineJoin='round';ctx.lineCap='round';ctx.stroke();points.forEach((p,i)=>{if(i===points.length-1||i%3===0){ctx.beginPath();ctx.arc(p.x,p.y,3.2,0,Math.PI*2);ctx.fillStyle='#fff';ctx.fill();ctx.strokeStyle=accentColor;ctx.lineWidth=2;ctx.stroke();}});
  ctx.fillStyle=labelColor;ctx.font='8px DM Sans';ctx.textAlign='center';rows.forEach((r,i)=>{if(i%Math.max(1,Math.ceil(rows.length/7))===0||i===rows.length-1){const d=new Date(r.sold_at+'T00:00:00');ctx.fillText(d.toLocaleDateString(undefined,{month:'short',day:'numeric'}),points[i].x,h-8);}});
}

function renderInventory(){
  const products=state.products;const total=products.length,low=products.filter(p=>statusFor(p)==='low').length,out=products.filter(p=>statusFor(p)==='out').length,value=products.reduce((n,p)=>n+p.on_hand*p.unit_cost,0);
  $('#inventory-metrics').innerHTML=[metric('ACTIVE PRODUCTS',total,'Products in your catalog','◫','blue'),metric('TOTAL STOCK VALUE',money(value),'Current on-hand value','◆','mint'),metric('LOW STOCK',low,'At or below minimum','!','amber'),metric('OUT OF STOCK',out,'Zero available quantity','×','violet')].join('');
  const cats=[...new Set(products.map(p=>p.category||'Uncategorized'))].sort();const catSel=$('#category-filter');const old=catSel.value;catSel.innerHTML='<option value="">All categories</option>'+cats.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');catSel.value=cats.includes(old)?old:'';
  filterInventory();
  const moves=state.movements.slice(0,10);$('#movement-body').innerHTML=moves.length?moves.map(m=>`<tr><td>${dateTime(m.created_at)}</td><td>${esc(m.product_name)}</td><td>${esc(m.movement_type.replaceAll('_',' '))}</td><td class="${m.quantity_delta>=0?'quantity-positive':'quantity-negative'}">${m.quantity_delta>=0?'+':''}${num(m.quantity_delta,3)} ${esc(m.stock_unit)}</td><td>${esc(m.note||'—')}</td></tr>`).join(''):`<tr><td colspan="5"><div class="empty-state">No stock movements recorded yet.</div></td></tr>`;
}
function filterInventory(){
  const q=($('#product-search')?.value||'').toLowerCase(),cat=$('#category-filter')?.value||'',f=$('#stock-filter')?.value||'';
  const rows=state.products.filter(p=>(p.name.toLowerCase().includes(q)||p.sku.toLowerCase().includes(q))&&(!cat||p.category===cat)&&(!f||statusFor(p)===f));
  $('#inventory-body').innerHTML=rows.length?rows.map(p=>{const s=statusFor(p);return `<tr><td>${productCell(p)}</td><td><span class="muted">${esc(p.sku)}</span></td><td>${esc(p.category)}</td><td><b>${num(p.on_hand,3)} ${esc(p.stock_unit)}</b></td><td>${num(p.min_stock,3)} ${esc(p.stock_unit)}</td><td>${money(p.unit_cost)}</td><td class="currency-cell">${money(p.stock_value??p.on_hand*p.unit_cost)}</td><td><span class="${statusClass(s)}">${statusLabel(s)}</span></td><td><div class="row-actions"><button class="icon-action" data-action="edit-product" data-id="${p.id}" title="Edit">${miniIcon('✎')}</button><button class="icon-action" data-action="adjust-product" data-id="${p.id}" title="Adjust stock">${miniIcon('↗')}</button></div></td></tr>`}).join(''):`<tr><td colspan="9"><div class="empty-state">No products match. Add a product or change your filters.</div></td></tr>`;
  $('#inventory-footer').textContent=`Showing ${rows.length} of ${state.products.length} products`;
}

function renderAnalytics(){
  if(!state.analytics)return;const a=state.analytics;
  $('#analytics-metrics').innerHTML=[metric('REVENUE · 7 DAYS',money(a.revenue_7d),'Recent week','↗','mint'),metric('UNITS SOLD · 7 DAYS',num(a.units_7d,2),'Across imported sales','◫','blue'),metric('WEEK-OVER-WEEK',a.revenue_change_pct===null?'—':`${a.revenue_change_pct>0?'+':''}${a.revenue_change_pct}%`,'Revenue comparison','⌁','violet'),metric('RECORDED WASTE COST',money(a.waste_cost_28d),'Last 28 days','◌','amber')].join('');
  drawLineChart($('#analytics-chart'),a.daily||[],'revenue');
  const best=a.best_sellers_28d||[],max=Math.max(1,...best.map(x=>x.quantity));
  $('#top-products').innerHTML=best.length?best.map((p,i)=>`<div class="rank-row"><div class="rank-num">${i+1}</div><div><div class="rank-name">${esc(p.name)}</div><div class="rank-bar"><span style="width:${Math.max(3,p.quantity/max*100)}%"></span></div></div><div class="rank-val">${num(p.quantity,1)} ${esc(p.stock_unit)}</div></div>`).join(''):`<div class="empty-state">Import sales to see your best sellers.</div>`;
  const slow=a.slow_movers_28d||[];$('#slow-products').innerHTML=slow.length?slow.map(p=>`<tr><td>${productCell(p)}</td><td>${esc(p.sku)}</td><td>${num(p.on_hand,2)} ${esc(p.stock_unit)}</td><td>${num(p.sold_28d,2)} ${esc(p.stock_unit)}</td><td><span class="${p.sold_28d<=0?'status status-out':'status status-low'}">${p.sold_28d<=0?'No sales':'Review demand'}</span></td></tr>`).join(''):`<tr><td colspan="5"><div class="empty-state">No slow-moving products identified yet.</div></td></tr>`;
}
async function loadAnalytics(){try{state.analytics=await api('/api/analytics');renderAnalytics()}catch(e){toast(e.message,'error')}}
async function loadInventory(){try{[state.products,state.movements]=await Promise.all([api('/api/products'),api('/api/movements')]);renderInventory()}catch(e){toast(e.message,'error')}}

function renderPurchasing(){
  const recs=state.recommendations||[],needed=recs.filter(r=>r.recommended_quantity>0);
  const est=needed.reduce((n,r)=>n+r.estimated_cost,0);
  $('#purchase-metrics').innerHTML=[metric('PRODUCTS REVIEWED',recs.length,'Active catalog','◫','blue'),metric('SUGGESTED REORDERS',needed.length,'Require a purchase decision','✳','mint'),metric('ESTIMATED ORDER VALUE',money(est),'Based on available unit costs','↗','violet'),metric('MISSING SUPPLIER LINKS',recs.filter(r=>r.recommended_quantity>0&&!r.supplier_id).length,'Assign suppliers for better planning','!','amber')].join('');
  const all=state.selectedRecommendations;
  if(!state.selectionInitialized && needed.length){needed.forEach(r=>all.add(r.product_id));state.selectionInitialized=true;}
  for(const id of [...all])if(!needed.some(r=>r.product_id===id))all.delete(id);
  $('#recommendation-body').innerHTML=recs.length?recs.map(r=>`<tr><td><input class="recommendation-checkbox" type="checkbox" data-rec-id="${r.product_id}" ${r.recommended_quantity>0&&state.selectedRecommendations.has(r.product_id)?'checked':''} ${r.recommended_quantity<=0?'disabled':''}></td><td>${productCell(r)}</td><td><b>${num(r.on_hand,2)} ${esc(r.stock_unit)}</b></td><td>${num(r.incoming,2)} ${esc(r.stock_unit)}</td><td>${r.forecast_demand===null?'—':`${num(r.forecast_demand,2)} ${esc(r.stock_unit)}`}</td><td>${r.recommended_quantity>0?`<b class="quantity-positive">${num(r.purchase_quantity,2)} ${esc(r.purchase_unit)}</b><div class="product-meta">${num(r.recommended_quantity,2)} ${esc(r.stock_unit)} stock</div>`:'—'}</td><td>${esc(r.supplier_name)}</td><td>${r.recommended_quantity>0?money(r.estimated_cost):'—'}</td><td><span class="confidence confidence-${r.confidence}">${esc(r.confidence)}</span></td></tr>`).join(''):`<tr><td colspan="9"><div class="empty-state">Add products and import sales history to generate purchasing recommendations.</div></td></tr>`;
  $('#recommendation-footer').textContent=`${needed.length} suggested reorders · ${money(est)} estimated total · All quantities require owner review`;
  $('#select-all-recs').checked=needed.length>0&&needed.every(r=>state.selectedRecommendations.has(r.product_id));
}
async function loadPurchasing(){try{state.recommendations=await api('/api/recommendations');renderPurchasing()}catch(e){toast(e.message,'error')}}
async function runForecast(){try{const res=await api('/api/forecasts/run',{method:'POST',body:{horizon_days:Number(state.settings.forecast_horizon_days||14)}});toast(`Forecast recalculated for ${res.forecasts.length} products`);await loadPurchasing()}catch(e){toast(e.message,'error')}}
async function createSelectedOrders(){
  const selected=state.recommendations.filter(r=>state.selectedRecommendations.has(r.product_id)&&r.recommended_quantity>0);
  if(!selected.length){toast('Select at least one suggested product.','error');return}
  const groups=new Map();for(const r of selected){const key=r.supplier_id||'none';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r)}
  const minimumWarnings=[];
  for(const [supplierId,items] of groups){
    if(supplierId==='none')continue;
    const supplier=state.suppliers.find(s=>s.id===Number(supplierId));
    const groupTotal=items.reduce((n,r)=>n+r.estimated_cost,0);
    if(supplier&&Number(supplier.minimum_order_value)>groupTotal)minimumWarnings.push(`${supplier.name}: ${money(groupTotal)} selected vs ${money(supplier.minimum_order_value)} stated minimum`);
  }
  const warningText=minimumWarnings.length?`\n\nCheck supplier minimums:\n• ${minimumWarnings.join('\n• ')}`:'';
  if(!confirm(`Create ${groups.size} draft purchase order(s) for ${selected.length} product(s)? No supplier will be contacted automatically.${warningText}`))return;
  try{let count=0;for(const [supplier,items] of groups){await api('/api/purchase-orders',{method:'POST',body:{supplier_id:supplier==='none'?null:Number(supplier),items:items.map(r=>({product_id:r.product_id,quantity:r.recommended_quantity,unit_cost:r.unit_cost})),notes:'Generated from CutPilot purchasing recommendations'}});count++}state.selectedRecommendations.clear();toast(`${count} draft purchase order(s) created`);await refreshAll();go('orders')}catch(e){toast(e.message,'error')}
}

function renderOrders(){
  const orders=state.orders||[],draft=orders.filter(o=>o.status==='draft').length,open=orders.filter(o=>['approved','sent','partially_received'].includes(o.status)).length,total=orders.reduce((n,o)=>n+Number(o.total_estimate||0),0);
  $('#order-metrics').innerHTML=[metric('TOTAL ORDERS',orders.length,'All order records','▤','blue'),metric('DRAFT ORDERS',draft,'Awaiting review','◷','amber'),metric('OPEN ORDERS',open,'Approved or sent','↗','mint'),metric('ORDER VALUE',money(total),'All created orders','◆','violet')].join('');
  filterOrders();
}
function filterOrders(){const q=($('#order-search')?.value||'').toLowerCase(),status=$('#order-status-filter')?.value||'';const rows=state.orders.filter(o=>(o.order_number.toLowerCase().includes(q)||(o.supplier_name||'').toLowerCase().includes(q))&&(!status||o.status===status));
  $('#orders-body').innerHTML=rows.length?rows.map(o=>{const actions=[];if(o.status==='draft')actions.push(`<button class="icon-action" data-order-action="approve" data-id="${o.id}" title="Approve">${miniIcon('✓')}</button>`);if(['approved','draft'].includes(o.status))actions.push(`<button class="icon-action" data-order-action="send" data-id="${o.id}" title="Mark sent">${miniIcon('➤')}</button>`);if(['approved','sent','partially_received'].includes(o.status))actions.push(`<button class="icon-action" data-order-action="receive" data-id="${o.id}" title="Receive stock">↓</button>`);if(!['received','cancelled'].includes(o.status))actions.push(`<button class="icon-action" data-order-action="cancel" data-id="${o.id}" title="Cancel">×</button>`);actions.push(`<button class="icon-action" data-order-export="${o.id}" title="Export CSV">⇩</button>`);return `<tr><td><b>${esc(o.order_number)}</b></td><td>${esc(o.supplier_name||'Unassigned')}</td><td>${dateShort(o.created_at)}</td><td>${dateShort(o.expected_delivery)}</td><td>${o.item_count}</td><td class="currency-cell">${money(o.total_estimate)}</td><td><span class="${statusClass(o.status)}">${statusLabel(o.status)}</span></td><td><div class="row-actions">${actions.join('')}</div></td></tr>`}).join(''):`<tr><td colspan="8"><div class="empty-state">No purchase orders found. Create draft orders from Purchasing.</div></td></tr>`;
}
async function loadOrders(){try{state.orders=await api('/api/purchase-orders');renderOrders()}catch(e){toast(e.message,'error')}}
async function orderAction(id,action){
  try{
    if(action==='receive'){
      const order=await api(`/api/purchase-orders/${id}`);
      const items=order.items.map(item=>({...item,remaining:Number(item.quantity)-Number(item.received_quantity)}));
      showModal(`Receive ${order.order_number}`,`<form id="receive-order-form" class="modal-form">
        <div class="full"><p class="model-info">Enter the quantities actually received. You can receive part of an order now and the rest later. Only received quantities are added to inventory.</p></div>
        ${items.map(item=>`<label class="full">${esc(item.product_name)} · ${esc(item.stock_unit)}<input name="received_${item.id}" type="number" min="0" max="${item.remaining}" step="0.001" value="${item.remaining}" required><small>${num(item.received_quantity,3)} already received · ${num(item.remaining,3)} still outstanding</small></label>`).join('')}
        <label class="full">Batch expiry date (optional)<input name="expiry_date" type="date"></label>
        <div class="form-footer"><button type="button" class="btn btn-outline" data-close-modal>Cancel</button><button type="submit" class="btn btn-primary">Record received stock</button></div>
      </form>`,'PURCHASE RECEIVING');
      $('#receive-order-form').addEventListener('submit',async e=>{e.preventDefault();const f=Object.fromEntries(new FormData(e.currentTarget));const received={};for(const item of items)received[String(item.id)]=Number(f[`received_${item.id}`]||0);try{const result=await api(`/api/purchase-orders/${id}/receive`,{method:'POST',body:{expiry_date:f.expiry_date||null,received_quantities:received}});closeModal();toast(`Order ${result.order_number}: ${statusLabel(result.status).toLowerCase()}`);await refreshAll()}catch(err){toast(err.message,'error')}});
      return;
    }
    const messages={approve:'Approve this purchase order?',send:'Mark this order as sent to the supplier? (This does not email the supplier.)',cancel:'Cancel this purchase order?'};
    if(!confirm(messages[action]))return;
    const result=await api(`/api/purchase-orders/${id}/${action}`,{method:'POST',body:{}});toast(`Order ${result.order_number}: ${statusLabel(result.status).toLowerCase()}`);await refreshAll();
  }catch(e){toast(e.message,'error')}
}

function renderSuppliers(){
  $('#suppliers-grid').innerHTML=state.suppliers.length?state.suppliers.map(s=>`<article class="supplier-card"><div class="supplier-top"><div class="supplier-avatar">${esc(s.name.split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase())}</div><div><strong>${esc(s.name)}</strong><small>${esc(s.email||s.phone||'No contact details')}</small></div></div><div class="supplier-detail"><span>Lead time</span><b>${s.lead_time_days} day(s)</b></div><div class="supplier-detail"><span>Linked products</span><b>${s.product_count}</b></div><div class="supplier-detail"><span>Minimum order</span><b>${money(s.minimum_order_value)}</b></div></article>`).join(''):`<div class="empty-state">Add suppliers and link them to products to improve order recommendations.</div>`;
  $('#link-supplier').innerHTML='<option value="">Choose supplier</option>'+state.suppliers.map(s=>`<option value="${s.id}">${esc(s.name)}</option>`).join('');
  $('#link-product').innerHTML='<option value="">Choose product</option>'+state.products.map(p=>`<option value="${p.id}">${esc(p.name)} · ${esc(p.sku)}</option>`).join('');
}
async function loadSuppliers(){try{[state.suppliers,state.products]=await Promise.all([api('/api/suppliers'),api('/api/products')]);renderSuppliers()}catch(e){toast(e.message,'error')}}

function renderWaste(){
  const records=state.waste||[],total=records.reduce((n,w)=>n+Number(w.estimated_cost),0),qty=records.reduce((n,w)=>n+Number(w.quantity),0),last28=records.filter(w=>new Date(w.recorded_at)>=new Date(Date.now()-28*86400000));
  $('#waste-metrics').innerHTML=[metric('RECORDED WASTE COST',money(last28.reduce((n,w)=>n+Number(w.estimated_cost),0)),'Last 28 days','◌','amber'),metric('WASTE QUANTITY',num(last28.reduce((n,w)=>n+Number(w.quantity),0),2),'Last 28 days · mixed units','↘','violet'),metric('WASTE EVENTS',last28.length,'Last 28 days','▤','blue'),metric('ALL-TIME RECORDED COST',money(total),`${records.length} recorded events`,'◆','mint')].join('');
  $('#waste-body').innerHTML=records.length?records.map(w=>`<tr><td>${dateTime(w.recorded_at)}</td><td>${esc(w.product_name)}</td><td>${num(w.quantity,3)} ${esc(w.stock_unit)}</td><td>${esc(w.reason)}</td><td class="currency-cell">${money(w.estimated_cost)}</td><td>${esc(w.note||'—')}</td></tr>`).join(''):`<tr><td colspan="6"><div class="empty-state">No waste recorded yet. Use “Record waste” when stock is discarded.</div></td></tr>`;
}
async function loadWaste(){try{state.waste=await api('/api/waste');renderWaste()}catch(e){toast(e.message,'error')}}

function renderImportHistory(){const rows=state.imports||[];$('#import-history-list').innerHTML=rows.length?rows.slice(0,8).map(x=>`<div class="activity-row"><span class="activity-dot"></span><div><strong>${esc(x.filename)}</strong><small>${x.imported_count} imported · ${x.duplicate_count} duplicates · ${dateTime(x.imported_at)}</small></div></div>`).join(''):`<div class="empty-state compact">No imports yet.</div>`;}
async function loadImports(){try{state.imports=await api('/api/imports');renderImportHistory()}catch(e){toast(e.message,'error')}}

function renderSettings(){if(!state.settings)return;$('#setting-business').value=state.settings.business_name||'My Butcher Shop';$('#setting-currency').value=state.settings.currency||'USD';$('#setting-review').value=state.settings.review_period_days||7;$('#setting-horizon').value=state.settings.forecast_horizon_days||14;$('#setting-timezone').value=state.settings.business_timezone||'UTC';}
async function loadSettings(){try{state.settings=await api('/api/settings');renderSettings()}catch(e){toast(e.message,'error')}}

function renderAssistantMessage(text,role='bot',small=''){
  const wrapper=document.createElement('div');wrapper.className=`chat-message ${role}`;const avatar=document.createElement('div');avatar.className='chat-avatar';avatar.innerHTML=role==='bot'?miniIcon('✳'):'<span>CP</span>';const bubble=document.createElement('div');bubble.className='chat-bubble';const p=document.createElement('p');p.textContent=text;bubble.append(p);if(small){const meta=document.createElement('small');meta.textContent=small;bubble.append(meta)}wrapper.append(avatar,bubble);$('#chat-messages').append(wrapper);$('#chat-messages').scrollTop=$('#chat-messages').scrollHeight;
}
async function askAssistant(question){if(state.chatBusy||!question.trim())return;state.chatBusy=true;renderAssistantMessage(question,'user');$('#assistant-question').value='';const typing=document.createElement('div');typing.className='chat-message bot';typing.id='assistant-typing';typing.innerHTML=`<div class="chat-avatar">${miniIcon('✳')}</div><div class="chat-bubble">Checking your business data…</div>`;$('#chat-messages').append(typing);try{const result=await api('/api/assistant',{method:'POST',body:{question}});typing.remove();renderAssistantMessage(result.answer,'bot',`Source: ${result.source}`)}catch(e){typing.remove();renderAssistantMessage(`I couldn't retrieve that information: ${e.message}`,'bot')}finally{state.chatBusy=false}}

function productModal(product=null){const p=product||{};showModal(product?'Edit product':'Add product',`<form id="product-form" class="modal-form">
  <label class="full">Product name<input name="name" required value="${esc(p.name||'')}" placeholder="e.g. Chicken breast"></label>
  <label>SKU<input name="sku" value="${esc(p.sku||'')}" placeholder="Auto-generated if blank"></label>
  <label>Category<input name="category" value="${esc(p.category||'Uncategorized')}" placeholder="Poultry, Beef…"></label>
  <label>Stock unit<select name="stock_unit"><option value="kg" ${p.stock_unit==='kg'?'selected':''}>Kilogram (kg)</option><option value="g" ${p.stock_unit==='g'?'selected':''}>Gram (g)</option><option value="piece" ${p.stock_unit==='piece'?'selected':''}>Piece</option><option value="lb" ${p.stock_unit==='lb'?'selected':''}>Pound (lb)</option></select></label>
  <label>Purchase unit<input name="purchase_unit" value="${esc(p.purchase_unit||p.stock_unit||'kg')}" placeholder="kg, carton, case"></label>
  <label>Conversion factor<input name="conversion_factor" type="number" min="0.0001" step="0.0001" value="${p.conversion_factor||1}" required><small>Stock units in one purchase unit</small></label>
  <label>Minimum stock<input name="min_stock" type="number" min="0" step="0.001" value="${p.min_stock||0}" required></label>
  <label>Pack multiple<input name="pack_size" type="number" min="0.001" step="0.001" value="${p.pack_size||1}" required><small>Purchase units per order multiple</small></label>
  <label>Shelf life (days)<input name="shelf_life_days" type="number" min="1" value="${p.shelf_life_days||3}"></label>
  <label>Unit purchase cost<input name="unit_cost" type="number" min="0" step="0.01" value="${p.unit_cost||0}"></label>
  <label>Unit selling price<input name="unit_price" type="number" min="0" step="0.01" value="${p.unit_price||0}"></label>
  ${product?'':'<label class="full">Opening stock<input name="opening_stock" type="number" min="0" step="0.001" value="0"></label>'}
  <div class="form-footer"><button type="button" class="btn btn-outline" data-close-modal>Cancel</button><button class="btn btn-primary" type="submit">${product?'Save changes':'Create product'}</button></div></form>`,'PRODUCT CATALOG');
  $('#product-form').addEventListener('submit',async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.currentTarget));['conversion_factor','min_stock','pack_size','shelf_life_days','unit_cost','unit_price','opening_stock'].forEach(k=>{if(data[k]!==undefined)data[k]=Number(data[k])});try{await api(product?`/api/products/${p.id}`:'/api/products',{method:product?'PUT':'POST',body:data});closeModal();toast(product?'Product updated':'Product created');await refreshAll()}catch(err){toast(err.message,'error')}});
}
function stockModal(productId=null){const product=state.products.find(p=>p.id===Number(productId));showModal('Adjust inventory',`<form id="stock-form" class="modal-form">
<label class="full">Product<select name="product_id" required>${state.products.map(p=>`<option value="${p.id}" ${product&&product.id===p.id?'selected':''}>${esc(p.name)} · ${num(p.on_hand,2)} ${esc(p.stock_unit)} on hand</option>`).join('')}</select></label>
<label>Action<select name="action"><option value="receive">Receive stock (+)</option><option value="remove">Remove stock (−)</option><option value="set">Set physical count</option></select></label>
<label>Quantity<input name="quantity" type="number" min="0" step="0.001" required placeholder="0.000"></label>
<label class="full">Expiry date (optional)<input name="expiry_date" type="date"></label>
<label class="full">Note<input name="note" placeholder="Delivery, stock count, correction…"></label>
<div class="form-footer"><button type="button" class="btn btn-outline" data-close-modal>Cancel</button><button class="btn btn-primary" type="submit">Save stock update</button></div></form>`,'STOCK LEDGER');
  $('#stock-form').addEventListener('submit',async e=>{e.preventDefault();const f=Object.fromEntries(new FormData(e.currentTarget));f.product_id=Number(f.product_id);f.quantity=Number(f.quantity);try{await api('/api/stock/adjust',{method:'POST',body:f});closeModal();toast('Stock balance updated');await refreshAll()}catch(err){toast(err.message,'error')}});
}
function supplierModal(){showModal('Add supplier',`<form id="supplier-form" class="modal-form">
<label class="full">Supplier name<input name="name" required placeholder="e.g. Fresh Farm Meats"></label>
<label>Contact name<input name="contact_name" placeholder="Contact person"></label><label>Email<input name="email" type="email" placeholder="orders@supplier.com"></label>
<label>Phone<input name="phone" placeholder="+1…"></label><label>Lead time (days)<input name="lead_time_days" type="number" min="0" max="365" value="2"></label>
<label>Minimum order value<input name="minimum_order_value" type="number" min="0" step="0.01" value="0"></label><label class="full">Notes<textarea name="notes" placeholder="Delivery schedule, terms, product range…"></textarea></label>
<div class="form-footer"><button type="button" class="btn btn-outline" data-close-modal>Cancel</button><button class="btn btn-primary" type="submit">Add supplier</button></div></form>`,'SUPPLIER NETWORK');
  $('#supplier-form').addEventListener('submit',async e=>{e.preventDefault();const f=Object.fromEntries(new FormData(e.currentTarget));f.lead_time_days=Number(f.lead_time_days);f.minimum_order_value=Number(f.minimum_order_value);try{await api('/api/suppliers',{method:'POST',body:f});closeModal();toast('Supplier added');await refreshAll()}catch(err){toast(err.message,'error')}});
}
function wasteModal(){showModal('Record wasted stock',`<form id="waste-form" class="modal-form">
<label class="full">Product<select name="product_id" required>${state.products.map(p=>`<option value="${p.id}">${esc(p.name)} · ${num(p.on_hand,2)} ${esc(p.stock_unit)} available</option>`).join('')}</select></label>
<label>Quantity<input name="quantity" type="number" min="0.001" step="0.001" required placeholder="0.000"></label>
<label>Reason<select name="reason"><option>Expired</option><option>Slow-moving stock</option><option>Preparation loss</option><option>Handling loss</option><option>Quality issue</option><option>Other</option></select></label>
<label class="full">Note<input name="note" placeholder="Optional details"></label>
<div class="form-footer"><button type="button" class="btn btn-outline" data-close-modal>Cancel</button><button type="submit" class="btn btn-primary">Record waste</button></div></form>`,'WASTE CONTROL');
  $('#waste-form').addEventListener('submit',async e=>{e.preventDefault();const f=Object.fromEntries(new FormData(e.currentTarget));f.product_id=Number(f.product_id);f.quantity=Number(f.quantity);try{await api('/api/waste',{method:'POST',body:f});closeModal();toast('Waste recorded and stock adjusted');await refreshAll()}catch(err){toast(err.message,'error')}});
}

const SALES_MAP_FIELDS = [
  ['date','Sale date',true],['product','Product name',false],['sku','SKU / barcode',false],['quantity','Quantity sold',true],['unit','Quantity unit',false],['unit_price','Selling price per unit',false],['total','Line total',false],['sale_id','Receipt / transaction ID',false]
];
const PRODUCT_MAP_FIELDS = [
  ['name','Product name',true],['sku','SKU / barcode',false],['category','Category',false],['stock_unit','Stock unit (kg, piece)',false],['purchase_unit','Purchase unit (carton, kg)',false],['conversion_factor','Stock units per purchase unit',false],['unit_cost','Purchase cost per stock unit',false],['unit_price','Selling price per stock unit',false],['opening_stock','Opening stock quantity',false],['min_stock','Minimum stock level',false],['pack_size','Supplier order multiple',false],['shelf_life_days','Shelf-life days',false]
];
function fileBase64(file){return file.arrayBuffer().then(buffer=>{const bytes=new Uint8Array(buffer);let binary='';for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000));return btoa(binary)})}
function renderMapping(containerId, headers, mapping, specs){
  const container=$(containerId); if(!container)return;
  container.innerHTML=specs.map(([field,label,required])=>{
    const selected=mapping?.[field]||'';
    return `<label class="mapping-field"><span>${esc(label)} ${required?'<em>Required</em>':'<small>Optional</small>'}</span><select data-map-field="${field}"><option value="">— Not in this file —</option>${headers.map(h=>`<option value="${esc(h)}" ${h===selected?'selected':''}>${esc(h)}</option>`).join('')}</select></label>`;
  }).join('');
}
function readMapping(containerId){const result={};$(`${containerId}`).querySelectorAll('[data-map-field]').forEach(el=>{result[el.dataset.mapField]=el.value||null});return result}
async function refreshMappedPreview(kind){
  const isProducts=kind==='products';
  const source=isProducts?state.productFileData:state.salesFileData;
  const mapping=readMapping(isProducts?'#product-mapping':'#sales-mapping');
  if(!source)return;
  try{
    const result=await api(isProducts?'/api/products/import/preview':'/api/imports/preview',{method:'POST',body:{...source,mapping}});
    if(isProducts){state.productImportPreview=result;renderProductImportPreview(result)}else{state.importPreview=result;renderImportPreview(result)}
  }catch(error){toast(error.message,'error')}
}
async function processFile(file, kind='sales'){
  if(!file)return;
  if(file.size>10*1024*1024){toast('File must be smaller than 10 MB.','error');return}
  if(!/\.(csv|xlsx|xlsm|xml)$/i.test(file.name)){toast('Choose a CSV, Excel .xlsx or supported XML file.','error');return}
  const isProducts=kind==='products';
  try{
    toast('Reading file and checking columns…');
    const source={filename:file.name,content_base64:await fileBase64(file)};
    if(isProducts)state.productFileData=source;else state.salesFileData=source;
    const result=await api(isProducts?'/api/products/import/preview':'/api/imports/preview',{method:'POST',body:source});
    if(isProducts){state.productImportPreview=result;$('#product-import-preview').classList.remove('hidden');renderProductImportPreview(result);$('#product-import-preview').scrollIntoView({behavior:'smooth',block:'start'})}
    else{state.importPreview=result;$('#upload-zone').classList.add('hidden');$('#import-preview').classList.remove('hidden');$('#import-result').classList.add('hidden');renderImportPreview(result)}
  }catch(error){toast(error.message,'error')}
}
function renderImportPreview(p){
  $('#import-preview').classList.remove('hidden');$('#preview-filename').textContent=p.filename;$('#preview-summary').textContent=`${p.row_count} valid rows · ${p.errors.length} rows need attention · ${p.headers.length} source columns`;
  renderMapping('#sales-mapping',p.headers,p.mapping,SALES_MAP_FIELDS);
  const rows=p.preview||[];$('#preview-table').innerHTML=rows.length?`<table class="data-table"><thead><tr><th>DATE</th><th>PRODUCT</th><th>SKU</th><th>QUANTITY</th><th>UNIT PRICE</th><th>LINE TOTAL</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.date)}</td><td>${esc(r.product)}</td><td>${esc(r.sku||'—')}</td><td>${num(r.quantity,3)} ${esc(r.unit||'')}</td><td>${money(r.unit_price)}</td><td>${money(r.total)}</td></tr>`).join('')}</tbody></table>`:'<div class="empty-state">No valid rows yet. Check the required column matches above.</div>';
  $('#preview-errors').classList.toggle('hidden',!p.errors.length);$('#preview-errors').innerHTML=p.errors.length?`<strong>${p.errors.length} row(s) will not be imported:</strong> ${p.errors.slice(0,8).map(x=>`Row ${x.row}: ${esc(x.error)}`).join(' · ')}${p.errors.length>8?` · and ${p.errors.length-8} more`:''}`:'';
  const warnings=$('#sales-preview-warnings');const warningParts=[];
  if(p.unmatched_products?.length)warningParts.push(`<strong>${p.unmatched_products.length} product identifier(s) were not found in your product catalogue.</strong> ${p.unmatched_products.slice(0,8).map(esc).join(', ')}. Import the product catalogue first or correct the SKU/product matches. If you continue, CutPilot will create these as new products with zero opening stock and zero purchase cost; profitability and stock recommendations for them will be incomplete until you edit them.`);
  const noRevenue=(p.rows||[]).filter(r=>Number(r.total||0)<=0).length;
  if(noRevenue)warningParts.push(`<strong>${noRevenue} sales row(s) have no selling price or line total.</strong> They can be imported, but will contribute zero revenue. Map a price or total column if your POS export contains one.`);
  if(warningParts.length){warnings.classList.remove('hidden');warnings.innerHTML=warningParts.join('<br><br>')}else{warnings.classList.add('hidden');warnings.textContent=''}
  $('#step-preview').classList.add('active');$('#confirm-import').disabled=!p.row_count;
}
function renderProductImportPreview(p){
  $('#product-import-preview').classList.remove('hidden');$('#product-preview-filename').textContent=p.filename;$('#product-preview-summary').textContent=`${p.row_count} valid product rows · ${p.errors.length} rows need attention · ${p.headers.length} source columns`;
  renderMapping('#product-mapping',p.headers,p.mapping,PRODUCT_MAP_FIELDS);
  const rows=p.preview||[];
  $('#product-preview-table').innerHTML=rows.length?`<table class="data-table"><thead><tr><th>PRODUCT</th><th>SKU</th><th>CATEGORY</th><th>STOCK UNIT</th><th>OPENING STOCK</th><th>BUY COST</th><th>SELL PRICE</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${esc(r.name)}</strong></td><td>${esc(r.sku||'Generated from name')}</td><td>${esc(r.category)}</td><td>${esc(r.stock_unit)}</td><td>${num(r.opening_stock,3)}</td><td>${money(r.unit_cost)}</td><td>${money(r.unit_price)}</td></tr>`).join('')}</tbody></table>`:'<div class="empty-state">No valid product rows. Map the required Product name column above.</div>';
  $('#product-preview-errors').classList.toggle('hidden',!p.errors.length);$('#product-preview-errors').innerHTML=p.errors.length?`<strong>${p.errors.length} row(s) need correction:</strong> ${p.errors.slice(0,8).map(x=>`Row ${x.row}: ${esc(x.error)}`).join(' · ')}${p.errors.length>8?` · and ${p.errors.length-8} more`:''}`:'';
  const productWarnings=[];const missingCost=(p.rows||[]).filter(r=>Number(r.unit_cost||0)<=0).length;const missingPrice=(p.rows||[]).filter(r=>Number(r.unit_price||0)<=0).length;
  if(missingCost)productWarnings.push(`${missingCost} product(s) have no purchase cost. Gross-profit and stock-value estimates will be incomplete.`);
  if(missingPrice)productWarnings.push(`${missingPrice} product(s) have no selling price. Add prices before relying on margin analysis.`);
  const pw=$('#product-preview-warnings');if(productWarnings.length){pw.classList.remove('hidden');pw.innerHTML=`<strong>Check these product details:</strong> ${productWarnings.map(esc).join(' ')}`}else{pw.classList.add('hidden');pw.textContent=''}
  $('#product-confirm-import').disabled=!p.row_count;
}
async function confirmImport(){
  const p=state.importPreview;if(!p)return;const btn=$('#confirm-import');btn.disabled=true;btn.textContent='Importing…';
  try{const result=await api('/api/imports/confirm',{method:'POST',body:{filename:p.filename,file_hash:p.file_hash,rows:p.rows,apply_to_stock:$('#apply-stock-check').checked}});state.importPreview=null;$('#import-preview').classList.add('hidden');$('#import-result').classList.remove('hidden');$('#import-result').innerHTML=`<div class="result-icon">✓</div><h3>Sales import completed</h3><p><strong>${result.imported}</strong> new sales rows added · ${result.duplicates} duplicates ignored · ${result.errors.length} rows skipped.<br>${result.apply_to_stock?'Imported quantities were deducted from inventory.':'Sales were added to analytics without changing current stock.'}</p><button class="btn btn-primary" id="go-analytics">View sales analytics →</button>`;$('#go-analytics').addEventListener('click',()=>go('analytics'));$('#step-done').classList.add('active');toast(`${result.imported} sales rows imported`);await refreshAll();}
  catch(e){toast(e.message,'error')}finally{btn.disabled=false;btn.innerHTML='Confirm import <span>→</span>'}
}
async function confirmProductImport(){
  const p=state.productImportPreview;if(!p)return;const btn=$('#product-confirm-import');btn.disabled=true;btn.textContent='Importing…';
  try{const result=await api('/api/products/import/confirm',{method:'POST',body:{rows:p.rows,update_existing_stock:$('#update-existing-stock-check').checked}});state.productImportPreview=null;$('#product-import-preview').classList.add('hidden');toast(`${result.created} products added · ${result.updated} updated · ${result.errors.length} row errors`);if(result.errors.length){showModal('Product import report',`<p>${result.created} added · ${result.updated} updated. ${result.errors.length} row(s) could not be imported.</p><div class="preview-errors">${result.errors.slice(0,12).map(x=>`Row ${x.row}: ${esc(x.error)}`).join('<br>')}</div>`,'IMPORT RESULTS')}await refreshAll();go('inventory');}
  catch(error){toast(error.message,'error')}finally{btn.disabled=false;btn.textContent='Import product catalog →'}
}

function bindEvents(){
  $('#theme-toggle').addEventListener('click',()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark'));
  $$('.nav-item[data-page]').forEach(el=>el.addEventListener('click',()=>go(el.dataset.page)));
  $$('[data-goto]').forEach(el=>el.addEventListener('click',()=>go(el.dataset.goto)));
  $('#mobile-menu').addEventListener('click',()=>$('#sidebar').classList.toggle('open'));
  $('#modal-close').addEventListener('click',closeModal);$('#modal-backdrop').addEventListener('click',e=>{if(e.target.id==='modal-backdrop')closeModal()});
  $('#modal-body').addEventListener('click',e=>{if(e.target.closest('[data-close-modal]'))closeModal()});
  $('#quick-import').addEventListener('click',()=>go('imports'));
  $('#load-demo').addEventListener('click',async()=>{if(!confirm('Load demo data into this empty workspace? Demo data can only be loaded into an empty workspace.'))return;try{const r=await api('/api/demo/seed',{method:'POST',body:{}});toast(r.message);await refreshAll()}catch(e){toast(e.message,'error')}});
  $('#add-product-btn').addEventListener('click',()=>productModal());
  $('#import-products-btn').addEventListener('click',()=>{go('imports');$('#products-file').click()});
  $('#import-products-page-btn')?.addEventListener('click',()=>$('#products-file').click());
  $('#products-file').addEventListener('change',e=>{processFile(e.target.files[0],'products');e.target.value=''});
  $('#product-mapping').addEventListener('change',()=>refreshMappedPreview('products'));
  $('#product-replace-file').addEventListener('click',()=>$('#products-file').click());
  $('#product-cancel-import').addEventListener('click',()=>{$('#product-import-preview').classList.add('hidden');state.productImportPreview=null;state.productFileData=null});
  $('#product-confirm-import').addEventListener('click',confirmProductImport);
  $('#stock-adjust-btn').addEventListener('click',()=>state.products.length?stockModal():toast('Add a product first.','error'));
  $('#product-search').addEventListener('input',filterInventory);$('#category-filter').addEventListener('change',filterInventory);$('#stock-filter').addEventListener('change',filterInventory);
  $('#inventory-body').addEventListener('click',e=>{const b=e.target.closest('[data-action]');if(!b)return;const p=state.products.find(x=>x.id===Number(b.dataset.id));if(b.dataset.action==='edit-product')productModal(p);else stockModal(p.id)});
  $('#export-sales').addEventListener('click',()=>window.location.href='/api/export/sales');
  $('#sales-file').addEventListener('change',e=>{processFile(e.target.files[0],'sales');e.target.value=''});$('#sales-mapping').addEventListener('change',()=>refreshMappedPreview('sales'));$('#upload-zone').addEventListener('dragover',e=>{e.preventDefault();$('#upload-zone').classList.add('dragging')});$('#upload-zone').addEventListener('dragleave',()=>$('#upload-zone').classList.remove('dragging'));$('#upload-zone').addEventListener('drop',e=>{e.preventDefault();$('#upload-zone').classList.remove('dragging');processFile(e.dataTransfer.files[0],'sales')});
  $('#replace-file').addEventListener('click',()=>{$('#import-preview').classList.add('hidden');$('#upload-zone').classList.remove('hidden');$('#sales-file').value='';state.salesFileData=null;state.importPreview=null});$('#cancel-import').addEventListener('click',()=>{$('#import-preview').classList.add('hidden');$('#upload-zone').classList.remove('hidden');state.importPreview=null;state.salesFileData=null});$('#confirm-import').addEventListener('click',confirmImport);
  $('#analytics-refresh').addEventListener('click',loadAnalytics);$('#run-forecast').addEventListener('click',runForecast);$('#create-orders').addEventListener('click',createSelectedOrders);
  $('#recommendation-body').addEventListener('change',e=>{const cb=e.target.closest('[data-rec-id]');if(!cb)return;const id=Number(cb.dataset.recId);if(cb.checked)state.selectedRecommendations.add(id);else state.selectedRecommendations.delete(id);renderPurchasing()});
  $('#select-all-recs').addEventListener('change',e=>{for(const r of state.recommendations){if(r.recommended_quantity>0){if(e.target.checked)state.selectedRecommendations.add(r.product_id);else state.selectedRecommendations.delete(r.product_id)}}renderPurchasing()});
  $('#select-needed').addEventListener('click',()=>{state.recommendations.filter(r=>r.recommended_quantity>0).forEach(r=>state.selectedRecommendations.add(r.product_id));renderPurchasing()});
  $('#order-search').addEventListener('input',filterOrders);$('#order-status-filter').addEventListener('change',filterOrders);
  $('#orders-body').addEventListener('click',e=>{const action=e.target.closest('[data-order-action]');const exp=e.target.closest('[data-order-export]');if(action)orderAction(Number(action.dataset.id),action.dataset.orderAction);if(exp)window.location.href=`/api/purchase-orders/${exp.dataset.orderExport}/export`});
  $('#add-supplier-btn').addEventListener('click',supplierModal);
  $('#supplier-link-form').addEventListener('submit',async e=>{e.preventDefault();const f=Object.fromEntries(new FormData(e.currentTarget));['supplier_id','product_id'].forEach(k=>f[k]=Number(f[k]));['unit_cost','minimum_quantity'].forEach(k=>f[k]=Number(f[k]));if(f.lead_time_days==='')delete f.lead_time_days;else f.lead_time_days=Number(f.lead_time_days);try{await api('/api/supplier-products',{method:'POST',body:f});toast('Supplier product link saved');await refreshAll()}catch(err){toast(err.message,'error')}});
  $('#record-waste-btn').addEventListener('click',()=>state.products.length?wasteModal():toast('Add a product first.','error'));
  $('#assistant-form').addEventListener('submit',e=>{e.preventDefault();askAssistant($('#assistant-question').value)});
  $$('.suggested-questions button').forEach(b=>b.addEventListener('click',()=>askAssistant(b.dataset.question)));
  $('#settings-form').addEventListener('submit',async e=>{e.preventDefault();const f=Object.fromEntries(new FormData(e.currentTarget));f.review_period_days=Number(f.review_period_days);f.forecast_horizon_days=Number(f.forecast_horizon_days);try{state.settings=await api('/api/settings',{method:'PUT',body:f});toast('Settings saved');await refreshAll()}catch(err){toast(err.message,'error')}});
}

async function init(){
  setTheme(document.documentElement.dataset.theme || 'light', false);
  bindEvents();
  try {
    const config = await fetch('/api/config').then(r=>r.json());
    if (config.mode === 'saas') {
      const response = await fetch('/api/auth/me');
      if (!response.ok) { window.location.href='/login?reason=expired'; return; }
      const account = await response.json();
      const user = account.user || {};
      const initials = (user.full_name || 'CutPilot').split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase();
      $('#account-avatar').textContent = initials;
      $('#profile-avatar').textContent = initials;
      $('#profile-name').textContent = user.full_name || 'Shop owner';
      $('#profile-role').textContent = `${user.role || 'owner'} · ${user.plan || 'starter'} plan`;
      $('#sidebar-business').textContent = user.business_name || 'Your shop';
      $('#runtime-status').innerHTML = '<span class="health-dot"></span>ACCOUNT WORKSPACE · PILOT';
      const modeTitle = $('#deployment-mode-title');
      if(modeTitle) modeTitle.textContent = 'Signed-in hosted account pilot';
      const modeDescription = $('#deployment-mode-description');
      if(modeDescription) modeDescription.innerHTML = '<b>Where is the data?</b> This shop has a separate SQLite workspace file on the hosting server. This is an early single-instance pilot, not a managed PostgreSQL production deployment.';
      if($('#deployment-app-value')) $('#deployment-app-value').textContent = 'Hosted service';
      if($('#deployment-db-value')) $('#deployment-db-value').textContent = 'Private SQLite file';
      if($('#deployment-account-value')) $('#deployment-account-value').textContent = 'Owner account';
      if($('#footer-mode-status')) $('#footer-mode-status').innerHTML = '<i class="health-dot"></i> Hosted account pilot · billing not active';
      const health = document.querySelector('.data-health');
      if(health){health.querySelector('.health-top').innerHTML='<span class="health-dot"></span><span>CLOUD WORKSPACE</span><span class="health-live">PRIVATE</span>';health.querySelector('p').textContent='You are signed in. Your business workspace is separated from other shops.';}
      $('#logout-btn').hidden = false;
      $('#logout-btn').addEventListener('click', async()=>{try{await fetch('/api/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});}finally{window.location.href='/';}});
    }
    await refreshAll();
  } catch(e) { toast(`Could not load CutPilot: ${e.message}`,'error'); }
  go('dashboard');
}
window.addEventListener('resize',()=>{if(state.page==='dashboard')drawLineChart($('#revenue-chart'),state.analytics?.daily||[],'revenue');if(state.page==='analytics')drawLineChart($('#analytics-chart'),state.analytics?.daily||[],'revenue')});
document.addEventListener('DOMContentLoaded',init);
