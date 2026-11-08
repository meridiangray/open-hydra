const q=new URLSearchParams(location.search).get('q')||'';document.querySelector('input[name=q]').value=q;
const norm=s=>s.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
fetch('search.json').then(r=>r.json()).then(rows=>{const w=norm(q).split(' ').filter(Boolean);
 const hit=rows.map(r=>{const ns=[r.t,...r.a,...(r.k||[]),...(r.k||[]).map(k=>k.split(':').slice(1).join(':'))].map(norm);const s=ns.some(n=>n==norm(q))?2:ns.some(n=>w.every(x=>n.includes(x)))?1:0;return[s,r]})
  .filter(x=>x[0]>0).sort((a,b)=>b[0]-a[0]||(a[1].x||0)-(b[1].x||0)||a[1].t.localeCompare(b[1].t)).slice(0,100);
 document.getElementById('hits').innerHTML=hit.length?hit.map(([s,r])=>`<li><a href="e-${r.b}.html">${r.t.replace(/</g,'&lt;')}</a> <span class=meta>${r.s}${r.x?' · outside scope':''}</span></li>`).join(''):'<li class=meta>No results. <a href=index.html>Back to the main page</a></li>'})
